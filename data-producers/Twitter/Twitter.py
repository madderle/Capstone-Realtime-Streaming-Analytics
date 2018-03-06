############################## Imports ########################################
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

#Twitter requirements
from tweepy.streaming import StreamListener
from tweepy import OAuthHandler
from tweepy import Stream
from tweepy import API

kinesis = boto3.client('kinesis', region_name='us-east-1')

#Mongo
from pymongo import MongoClient

#Connect to Redis-DataStore
REDIS = redis.Redis(host='data_store')

#Get Environment Variables
ACCESS_TOKEN = os.environ['ACCESS_TOKEN']
ACCESS_TOKEN_SECRET = os.environ['ACCESS_TOKEN_SECRET']
CONSUMER_KEY = os.environ['CONSUMER_KEY']
CONSUMER_SECRET = os.environ['CONSUMER_SECRET']

#Setup Mongo and create the database and collection
client = MongoClient('db-data')
db = client['stock_tweets']
coll_reference = db.twitter

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

########################## Build Dataframe ####################################
companies = json.loads(REDIS.get('companies').decode())
company_df = pd.DataFrame.from_dict(companies, orient='index')
company_df.index.name = 'Ticker'
company_df.columns=['Company']
#Add code to add ticker symbol
company_df['tweet_ticker']=company_df.index.map(lambda x: '$'+x)

tickers = company_df['tweet_ticker'].tolist()

####################### Set up Feature Flag ###################################


def get_feature_flag(feature):
    all_flags = pd.read_msgpack(REDIS.get("feature_flags"))

    try:
        return all_flags.get_value(feature, 'State')

    except:
        return 'Flag Not Found, not a valid feature flag'

########################### Define Functions #################################
attributes = ['created_at',
             'id_str',
             'text',
              'quote_count',
              'reply_count',
              'retweet_count',
              'favorite_count',
              'retweeted',
              'lang',
              ['user','name'],
              ['user','followers_count'],
              ['user','statuses_count'],
              ['user','screen_name']
               ]
def filter_attr(data):
    output = {}
    #Choose filter attributes
    for element in attributes:
        if isinstance(element, str):
            output[element]=data[element]
        #Handle Nested Attributes
        else:
            string = str(element[0])+'_'+str(element[1])
            output[string]=data[element[0]][element[1]]

    #Need to also add the company name to output dictionary.
    #Add all companies tweet applies to in list
    attached_company = []

    for company in tickers:
        if data['text'].find(company) > -1:
            attached_company.append(company[1:])


    output['Company']=attached_company

    return output

#This is a basic listener that just prints received tweets to stdout.
class TweetListener(StreamListener):

    def on_data(self, data):
        try:
            if int(REDIS.get('Data_On')) == 1:
                datajson = json.loads(data)
                filtered = filter_attr(datajson)
                #Check to see if a valid tweet
                if filtered['Company'] and filtered['lang']=='en':

                    print(filtered)
                    #Add counter to count stocks.
                    REDIS.incr('Twitter_Stock_Count')
                     # --------- Insert into MongoDB -------------------
                    if int(get_feature_flag('database_stream_write'))==1:
                        coll_reference.insert_one(filtered)
                    #---------- Insert to Kinesis Stream --------------
                    if int(get_feature_flag('kinesis_stream_write'))==1:
                        response = kinesis.put_record(StreamName="Twitter_Stream", Data=json.dumps(filtered), PartitionKey="partitionkey")
                    return True

        except Exception as e:
            print(e)

    def on_error(self, status):
        error_string = 'The error code is: ' + repr(status)
        print(error_string)
        #Continue even if there is an error
        #Need to publish the error to the redies error handler in manager
        #Send Start event
        send_event('Twitter', 'Error', error_string)
        #Need to think about if I want to continue running
        return True


#Setup Log

global past_tweet_count
past_tweet_count = 0



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
    current_tweet_count = int(REDIS.get('Twitter_Stock_Count'))

    global past_tweet_count
    tweet_count_diff = current_tweet_count - past_tweet_count
    past_tweet_count = current_tweet_count

    #Send the log event
    send_log(source='Twitter',current_count = current_tweet_count, count_diff=tweet_count_diff)
    print('Logged Data')

############################# Execute ########################################
REDIS.set('Twitter_Stock_Count', 0)

#This handles Twitter authetication and the connection to Twitter Streaming API
tweetlist = TweetListener(api=API(wait_on_rate_limit=True,wait_on_rate_limit_notify=True))
auth = OAuthHandler(CONSUMER_KEY,CONSUMER_SECRET)
auth.set_access_token(ACCESS_TOKEN,ACCESS_TOKEN_SECRET)
stream = Stream(auth, tweetlist)

#Filters by the ticker names
print('Filtering: ' + str(tickers))
stream.filter(track=tickers, async=True)

#Send Start event
send_event('Twitter', 'Activity', 'Data Source Started')

#Setup Schedule
schedule.clear()
schedule.every(30).seconds.do(log)

#Execute
while True:
    schedule.run_pending()
    #Cancel Schedule if an error occurs. and stop this loop.
    time.sleep(1)
