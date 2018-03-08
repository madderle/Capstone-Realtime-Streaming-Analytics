######################### Imports #############################################
import redis
import urllib.request
import json
import numpy as np
import pandas as pd
import schedule
import time
import boto3
from datetime import date, datetime
import traceback
import os

kinesis = boto3.client('kinesis', region_name='us-east-1')

#Mongo
from pymongo import MongoClient

#Connect to Redis-DataStore
REDIS = redis.Redis(host='data_store')

#Setup Mongo and create the database and collection
client = MongoClient('db-data')
db = client['stock_tweets']
coll_reference = db.iex


######################### Wait on Ready Flag ##################################

def get_ready_flag():
    try:
        return int(REDIS.get('Ready'))
    except:
        return 0

flag_value = get_ready_flag()

while flag_value==0:
    flag_value = get_ready_flag()
    time.sleep(500)

######################### Set up Feature Flag ################################


def get_feature_flag(feature):
    all_flags = pd.read_msgpack(REDIS.get("feature_flags"))

    try:
        return all_flags.get_value(feature, 'State')

    except:
        return 'Flag Not Found, not a valid feature flag'

######################## Define Functions #####################################
attributes = ['latestUpdate',
             'companyName',
             'latestPrice',
              'latestVolume',
              'marketCap',
              'open',
              'previousClose',
              'sector',
              'high',
              'low',
              'ytdChange',
              'peRatio',
              'week52High',
              'week52Low'
               ]

#Select interesting stock attributes.
def filter_stock_attributes(data):
    output = {}
    #Choose filter attributes
    for element in attributes:
        output[element]=data[element]

    #Convert time
    ctime = output['latestUpdate']/1000
    new_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ctime))
    output['latestUpdate']= new_time

    return output


#Create function to fetch the stock data. This is to prepare for the schedule.

def fetch_stock_data(stocks=[]):
    try:
        #Only pull stock info if the DataFlag is set.
        if int(REDIS.get('Data_On')) == 1:

            for ticker in stocks:
                url = "https://api.iextrading.com/1.0/stock/{}/quote".format(ticker)
                response = urllib.request.urlopen(url)
                str_response = response.read().decode('utf-8')
                obj = json.loads(str_response)
                filtered = filter_stock_attributes(obj)
                filtered['Ticker'] = ticker
                #Add counter to count stocks.
                REDIS.incr('IEX_Stock_Count')
                #<------ Insert into MongoDb ----------->
                if int(get_feature_flag('database_stream_write'))==1:
                    coll_reference.insert_one(filtered)

                #<----- Insert to Kinesis Stream ------->
                if int(get_feature_flag('kinesis_stream_write'))==1:
                    response = kinesis.put_record(StreamName="IEX_Stream", Data=json.dumps(filtered), PartitionKey="partitionkey")
                # print('---------------------------------')
                # print(response)
                # print(filtered)
    except:
        print(traceback.format_exc())
        #Send Error event
        send_event('IEX', 'Error', 'Error occured, check stdout')

#Setup Log
global past_stock_count
past_stock_count = 0




# Redis Subscription setup
queue = REDIS.pubsub()
#Subscribe to the queues one for the events and one for the log
queue.subscribe('event_queue')
queue.subscribe('log_queue')


#Serialize datetime.
def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError ("Type %s not serializable" % type(obj))



#Code to log to the event queue
def send_event(source, kind, message):
    event_time = datetime.now()
    event_time = json_serial(event_time)
    event = {
            "event_time": event_time,
            "source": source,
            "kind" : kind,
            "message" : message
            }
    payload = json.dumps(event)
    REDIS.publish('event_queue', payload)

def send_log(source, current_count, count_diff):
    log_time = datetime.now()
    log_time = json_serial(log_time)
    log = {
            "log_time": log_time,
            "source": source,
            "current_count" : current_count,
            "count_diff" : count_diff
            }
    payload = json.dumps(log)
    REDIS.publish('log_queue', payload)


#Send the log data to the Redis channel.
def log():
    #Need to log: Time, Source, Current Count, Count Diff
    #now = datetime.datetime.now()
    current_stock_count = int(REDIS.get('IEX_Stock_Count'))

    global past_stock_count
    stock_count_diff = current_stock_count - past_stock_count
    past_stock_count = current_stock_count

    #Send the log event
    send_log(source='IEX',current_count = current_stock_count, count_diff=stock_count_diff)

    print('Logged Data. Current Stock Count: {}'.format(current_stock_count))

############################### Execute #######################################
#Read Data-Store
companies = json.loads(REDIS.get('companies').decode())
stock_tickers = list(companies.keys())
REDIS.set('IEX_Stock_Count', 0)

#Setup Schedule
schedule.clear()
schedule.every(60).seconds.do(fetch_stock_data, stocks=stock_tickers)
schedule.every(65).seconds.do(log)

#Send Start event
send_event('IEX', 'Activity', 'Data Source Started')

#Execute
while True:
    schedule.run_pending()
    time.sleep(1)
