############### Initialize ###################

# Basics
from pymongo import MongoClient
import os
import numpy as np
import pandas as pd
import time
import boto3
import io
import warnings
warnings.filterwarnings('ignore')
import time
from datetime import date, datetime, timedelta
import subprocess
import redis
import schedule

# NLP
import nltk
import spacy
spacy.load('en')
from nltk.corpus import stopwords
import preprocessor as p

# Model Infrastructure
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD, PCA
from sklearn.pipeline import make_pipeline, Pipeline, FeatureUnion
from sklearn.preprocessing import Normalizer
from sklearn.model_selection import train_test_split
from sklearn.model_selection import GridSearchCV
from sklearn.metrics import classification_report
from sklearn.model_selection import StratifiedKFold
from sklearn.model_selection import cross_val_score
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.metrics import roc_auc_score, roc_curve, auc
from sklearn import metrics
import dill as pickle

# Models
from sklearn.linear_model import LogisticRegression

# Database Setup
import mysql.connector
from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import MetaData
from sqlalchemy import Table
from sqlalchemy import Column
from sqlalchemy import Integer, String, DateTime, Float

########## Database Setup #################
User = os.environ['DB_USER']
password = os.environ['DB_PWD']
dbname = os.environ['DB_NAME']
IP = os.environ['IP']

engine = create_engine('mysql+mysqlconnector://{}:{}@{}:3306/{}'.format(User,
                                                                        password, IP, dbname), echo=False)
conn = engine.connect()

# Check to see if the tables are created and if not, create them
meta = MetaData(engine)

# Create prediction table
if not engine.dialect.has_table(engine, 'daily_model_predictions'):
    print('Daily_Model_predictions Table does not exist')
    print('Daily_Model_predictions Table being created....')
    # Time, Source, Current Count, Count Diff
    t1 = Table('daily_model_predictions', meta,
               Column('run_time', DateTime, default=datetime.utcnow),
               Column('model_name', String(30)),
               Column('model_version_number', Integer),
               Column('Company', String(30)),
               Column('Prediction', Integer))
    t1.create()
else:
    print('Daily_Model_predictions Table Exists')

# Create table object
meta = MetaData(engine, reflect=True)
daily_model_predictions_table = meta.tables['daily_model_predictions']

# Write Function


def database_log(name, version_number, company, prediction):
    # Need to log these items to a database.

    ins = daily_model_predictions_table.insert().values(
        run_time=datetime.now(),
        model_name=name,
        model_version_number=version_number,
        Company=company,
        Prediction=prediction
    )
    conn.execute(ins)


# Download the Model
subprocess.run(['aws', 's3', 'cp',
                's3://brandyn-twitter-sentiment-analysis/Models/Daily_Stock_Prediction_latest.pk', './Models'])

# Load Model
filename = 'Daily_Stock_Prediction_latest.pk'

with open('./Models/' + filename, 'rb') as f:
    model = pickle.load(f)

##################### Connect to Database #######################
# Setup Mongo and create the database and collection
User = os.environ['MONGODB_USER']
password = os.environ['MONGODB_PASS']
IP = os.environ['IP']

client = MongoClient(IP, username=User, password=password)
db = client['stock_tweets']

# Grab references
twitter_coll_reference = db.twitter
iex_coll_reference = db.iex

# Create Time bound
time_bound = pd.to_datetime(datetime.utcnow() - timedelta(minutes=20))

####################### Get Model Version Number #############
query = '''
        SELECT model_version_number
        FROM model_scores
        ORDER BY run_time DESC
        LIMIT 1
        '''

model_version_number = conn.execute(query).fetchone()[0]

######################### Setup Redis #####################
# Connect to Redis-DataStore
REDIS = redis.Redis(host=IP)

######################## Define Functions #####################

# Build Twitter Data Frames


def get_twitter_data():
    # Create Data Frame from Mongo DB
    twitter_data = pd.DataFrame(list(twitter_coll_reference.find()))

    # Take a subset of the data, dont need all points to convert and this greatly speeds up
    twitter_data_subset = twitter_data.tail(2000)

    # Need to convert the created_at to a time stamp and set to index
    twitter_data_subset['created_at'] = pd.to_datetime(twitter_data_subset['created_at'])
    twitter_data_subset.index = twitter_data_subset['created_at']

    # Create time bounded dataframe
    twitter_data = twitter_data_subset[twitter_data_subset['created_at'] >= time_bound]

    # Delimited the Company List into separate rows
    delimited_twitter_data = []

    for item in twitter_data.itertuples():
        # twitter_dict={}
        for company in item[1]:
            twitter_dict = {}
            twitter_dict['created_at'] = item[0]
            twitter_dict['company'] = company
            twitter_dict['text'] = item[11]
            twitter_dict['user_followers_count'] = item[12]
            twitter_dict['user_name'] = item[13]
            twitter_dict['user_statuses_count'] = item[15]
            delimited_twitter_data.append(twitter_dict)

    delimited_twitter_df = pd.DataFrame(delimited_twitter_data)
    delimited_twitter_df.set_index('created_at', inplace=True)

    # Create hourly data frame
    twitter_delimited_daily = delimited_twitter_df.groupby(
        [pd.Grouper(freq="D"), 'company']).count()['text'].to_frame()
    twitter_delimited_daily.columns = ['Number_of_Tweets']

    # Concatenate the text with a space to not combine words.
    twitter_delimited_daily['text'] = delimited_twitter_df.groupby([pd.Grouper(freq="D"), 'company'])[
        'text'].apply(lambda x: ' '.join(x))
    # Number of Users
    twitter_delimited_daily['Number_of_Users'] = delimited_twitter_df.groupby(
        [pd.Grouper(freq="D"), 'company'])['user_name'].nunique()

    # Rename Index
    twitter_delimited_daily = twitter_delimited_daily.reindex(
        twitter_delimited_daily.index.rename(['Time', 'Company']))
    return twitter_delimited_daily

    # Build Stock Data Frames


def get_stock_data():
    stock_data = pd.DataFrame(list(iex_coll_reference.find()))

    # Take a subset of the data, dont need all points to convert and this greatly speeds up
    stock_data_subset = stock_data.tail(2000)

    # Need to convert the created_at to a time stamp
    stock_data_subset['latestUpdate'] = pd.to_datetime(stock_data_subset['latestUpdate'])
    stock_data_subset.index = stock_data_subset['latestUpdate']

    # Create time bounded dataframe
    stock_data = stock_data_subset[stock_data_subset['latestUpdate'] >= time_bound]

    # Create delimited dataframe
    stock_delimited_daily = stock_data.groupby([pd.Grouper(freq="D"), 'Ticker'])[
        'latestVolume'].mean().to_frame()
    stock_delimited_daily.columns = ['Mean_Volume']

    # Rename the Index
    stock_delimited_daily = stock_delimited_daily.reindex(
        stock_delimited_daily.index.rename(['Time', 'Company']))
    return stock_delimited_daily


    # Clean the Tweets
p.set_options(p.OPT.URL, p.OPT.EMOJI, p.OPT.MENTION, p.OPT.RESERVED, p.OPT.EMOJI, p.OPT.HASHTAG)


def preprocess_tweet(tweet):
    return p.clean(tweet)


# Make prediction function
# Create lemmatizer using spacy
lemmatizer = spacy.lang.en.English()


def make_predictions():
    # Only pull stock info if the DataFlag is set.
    if int(REDIS.get('Data_On')) == 1:

        print('Assembling Data Frames')
        # Call Functions
        twitter_delimited_daily = get_twitter_data()
        stock_delimited_daily = get_stock_data()

        # Combine Dataframes
        daily_df = pd.concat([twitter_delimited_daily, stock_delimited_daily], axis=1, join='inner')

        # To flatten after combined everything.
        daily_df.reset_index(inplace=True)

        print('Cleaning Data')
        # Clean the tweets, by removing special characters
        daily_df['Clean_text'] = daily_df['text'].apply(lambda x: preprocess_tweet(x))

        # Split Between Outcome and Features
        features = daily_df[['Number_of_Tweets', 'Number_of_Users', 'Mean_Volume', 'Clean_text']]

        print('Making Predictions')
        # Predictions
        y = model.predict(features)

        # Set Predictions to daily dataframe
        daily_df['predictions'] = y

        # Log to Database
        for item in daily_df.itertuples():
            version_number = int(model_version_number)
            company = item[2]
            prediction = item[8]
            database_log(filename, version_number, company, prediction)
        print('Made Prediction')
############################### Execute #######################################


# Setup Schedule
schedule.clear()
schedule.every(20).minutes.do(make_predictions)

# Execute
while True:
    schedule.run_pending()
    time.sleep(1)
