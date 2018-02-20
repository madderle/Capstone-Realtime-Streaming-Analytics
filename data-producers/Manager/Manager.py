############# Imports ##################################
import redis
import json
import schedule
import time
from datetime import date, datetime
import os

import mysql.connector
from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import MetaData
from sqlalchemy import Table
from sqlalchemy import Column
from sqlalchemy import Integer, String, DateTime

############# Redis Setup ##############################
# Connect to the DataStore
REDIS = redis.Redis(host='data_store')

# To setup the queue
queue = REDIS.pubsub()
# Subscribe to the queues one for the events and one for the log
queue.subscribe('event_queue')
queue.subscribe('log_queue')

#Create Ready Flag
REDIS.set('Ready', 0)

############# Setup Database ###########################
User = os.environ['DB_USER']
password = os.environ['DB_PWD']
dbname = os.environ['DB_NAME']


engine = create_engine('mysql+mysqlconnector://{}:{}@db:3306/{}'.format(User,
                                                                        password, dbname), echo=False)
conn = engine.connect()

# Check to see if the tables are created and if not, create them
meta = MetaData(engine)

# Create log table
if not engine.dialect.has_table(engine, 'log'):
    print('Log Table does not exist')
    print('Log Table being created....')
    # Time, Source, Current Count, Count Diff
    t1 = Table('log', meta,
               Column('log_time', DateTime, default=datetime.datetime.utcnow),
               Column('Source', String(30)),
               Column('Current_Count', Integer),
               Column('Count_Diff', Integer))
    t1.create()
else:
    print('Log Table Exists')

# Create event table
if not engine.dialect.has_table(engine, 'event'):
    print('Event Table does not exist')
    print('Event Table being created....')
    # Time, Source, Current Count, Count Diff
    t1 = Table('event', meta,
               Column('event_time', DateTime, default=datetime.datetime.utcnow),
               Column('Source', String(30)),
               Column('Kind', String(30)),
               Column('Message', String(8000)))
    t1.create()
else:
    print('Event Table Exists')

################## Define Functions ##############################

#Serialize datetime.
def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError ("Type %s not serializable" % type(obj))

# Create table object
meta = MetaData(engine, reflect=True)
log_table = meta.tables['log']


def database_log(log_data):
    #Need to log these items to a database.
    #Convert the data
    log_data = json.loads(log_data)
    print('------ Database Log Data --------')
    print(log_data)
    ins = log_table.insert().values(
            log_time = log_data['log_time'],
            Source = log_data['source'],
            Current_Count = log_data['current_count'],
            Count_Diff = log_data['count_diff']
               )
    conn.execute(ins)
    print('Logged Log Data')

#Create table object
event_table = meta.tables['event']

def database_event(event_data):
    #Need to log these items to a database.
    event_data = json.loads(event_data)

    ins = event_table.insert().values(
            event_time = event_data['event_time'],
            Source = event_data['source'],
            Kind=event_data['kind'],
            Message=event_data['message']
               )
    conn.execute(ins)
    print('Logged Event Data')

#Event Kind Types
#Activity, Error

#Manager will send itself a message when it turns data on and off
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

################# Set up the company list ########################
companies = {
    "AAPL":"Apple",
    "FB":"Facebook",
    "GOOG":"Google Alphabet C",
    "GOOGL":"Google Alphabet A",
    "AMZN":"Amazon",
    "MSFT":"Microsoft",
    "BAC":"Bank of America",
    "BA":"Boeing",
    "NFLX":"Netflix",
    "JPM":"JPMorgan Chase",
    "TSLA":"Tesla",
    "CSCO":"Cisco Systems",
    "XOM":"Exxon Mobil",
    "WFC":"Wells Fargo",
    "V":"Visa",
    "JNJ":"Johnson & Johnson",
    "PFE" :"Pfizer",
    "INTC":"Intel",
    "HD":"Home Depot",
    "C":"Citigroup",
    "UTX":"United Technologies",
    "CMCSA":"Comcast",
    "TWTR":"Twitter",
    "GE":"General Electric",
    "UNH":"United Health Group",
    "PCLN":"Priceline Group",
    "BABA":"Alibaba Group",
    "NVDA":"NVIDIA"
    }
REDIS.set('companies', json.dumps(companies))

############### Setup the Data ON Flag ###################
REDIS.set('Data_On', 0)

# Create Explicit Data On/Off Functions
def DataOn():
    REDIS.set('Data_On',1)
    send_event('Manager', 'Activity', 'Data flag On')


def DataOff():
    REDIS.set('Data_On',0)
    send_event('Manager', 'Activity', 'Data flag Off')


# Turn on if starts during open times
now = datetime.now()

if now.hour >= 14 and now.hour < 21:
    if now.hour = 14 and now.minute >= 30:
        DataOn()
    elif now.hour > 14:
        DataOn()

################ Setup Schedules ######################
# Since the market isnt open all day, want to control when turn data on and off

# Time in 24 hour clocks and UTC time
schedule.clear()
# Setup Data On/Off Schedule
schedule.every().monday.at("14:30").do(DataOn)
schedule.every().monday.at("21:00").do(DataOff)
schedule.every().tuesday.at("14:30").do(DataOn)
schedule.every().tuesday.at("21:00").do(DataOff)
schedule.every().wednesday.at("14:30").do(DataOn)
schedule.every().wednesday.at("21:00").do(DataOff)
schedule.every().thursday.at("14:30").do(DataOn)
schedule.every().thursday.at("21:00").do(DataOff)
schedule.every().friday.at("14:30").do(DataOn)
schedule.every().friday.at("21:00").do(DataOff)

########### Execute ############################
#Set Ready Flag
REDIS.set('Ready', 1)


while True:
    schedule.run_pending()

    #May need to add in another while loop here. But we shall see after testing.

    next_message = queue.get_message()
    #next_message = json.loads(queue.get_message()['data'].decode())
    if next_message:
        print('------ REDIS Message -------')
        print(next_message)
        #Ignore the initial 1 or 2 that comes out of the queue.
        try:
            payload = next_message['data'].decode()
            #check which queue
            if next_message['channel'].decode() == 'event_queue':
                #Call database_event function to log to database
                database_event(payload)
                #Eventually can check the kind of event and do different action if error.

            if next_message['channel'].decode() == 'log_queue':
                #Call database_log function to log to database
                database_log(payload)

        except:
            pass

    time.sleep(1)
