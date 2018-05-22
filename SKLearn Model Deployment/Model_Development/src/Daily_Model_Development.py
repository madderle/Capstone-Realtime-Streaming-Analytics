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
from datetime import date, datetime
import redis
import json


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

########################## Check Models Folder #################################
directory = './Models'

if not os.path.exists(directory):
    os.makedirs(directory)

####################################### Database Setup ###################################
User = os.environ['DB_USER']
password = os.environ['DB_PWD']
dbname = os.environ['DB_NAME']
IP = os.environ['IP']

engine = create_engine('mysql+mysqlconnector://{}:{}@{}:3306/{}'.format(User,
                                                                        password, IP, dbname), echo=False)
conn = engine.connect()

# Check to see if the tables are created and if not, create them
meta = MetaData(engine)

# Create log table
if not engine.dialect.has_table(engine, 'model_scores'):
    print('Model_Scores Table does not exist')
    print('Model_Scores Table being created....')
    # Time, Source, Current Count, Count Diff
    t1 = Table('model_scores', meta,
               Column('run_time', DateTime, default=datetime.utcnow),
               Column('model_name', String(30)),
               Column('model_version_number', Integer),
               Column('auc_score', Float),
               Column('build_time_sec', Float))
    t1.create()
else:
    print('Model_scores Table Exists')

# Create table object
meta = MetaData(engine, reflect=True)
model_scores_table = meta.tables['model_scores']

# Write Function


def database_log(name, version_number, auc, build_time):
    # Need to log these items to a database.

    ins = model_scores_table.insert().values(
        run_time=datetime.now(),
        model_name=name,
        model_version_number=version_number,
        auc_score=auc,
        build_time_sec=build_time
    )
    conn.execute(ins)


###################### Bring In Data #######################
# Setup Mongo and create the database and collection
User = os.environ['MONGODB_USER']
password = os.environ['MONGODB_PASS']
IP = os.environ['IP']

client = MongoClient(IP, username=User, password=password)
db = client['stock_tweets']

# Grab references
twitter_coll_reference = db.twitter
iex_coll_reference = db.iex

###################### Build Twitter Data Frames #####################


def create_twitter_data():
    # Create Data Frame
    twitter_data = pd.DataFrame(list(twitter_coll_reference.find()))

    # Need to convert the created_at to a time stamp and set to index
    twitter_data.index = pd.to_datetime(twitter_data['created_at'])

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

    ##################### Build Stock Data Frames ###########################


def create_stock_data():
    stock_data = pd.DataFrame(list(iex_coll_reference.find()))

    # Need to convert the created_at to a time stamp
    stock_data.index = pd.to_datetime(stock_data['latestUpdate'])
    stock_data['latestUpdate'] = pd.to_datetime(stock_data['latestUpdate'])
    # Group By hourly and stock price
    # Need to get the first stock price in teh hour, and then the last to take the difference to see how much change.
    stock_delimited_daily = stock_data.sort_values('latestUpdate').groupby(
        [pd.Grouper(freq="D"), 'Ticker']).first()['latestPrice'].to_frame()
    stock_delimited_daily.columns = ['First_Price']
    stock_delimited_daily['Last_Price'] = stock_data.sort_values(
        'latestUpdate').groupby([pd.Grouper(freq="D"), 'Ticker']).last()['latestPrice']

    # Then need to take the difference and turn into a percentage.
    stock_delimited_daily['Price_Percent_Change'] = ((stock_delimited_daily['Last_Price']
                                                      - stock_delimited_daily['First_Price']) / stock_delimited_daily['First_Price']) * 100

    # Need to also show Percent from open price
    stock_delimited_daily['Open_Price'] = stock_data.groupby(
        [pd.Grouper(freq="D"), 'Ticker'])['open'].mean()
    stock_delimited_daily['Price_Percent_Open'] = ((stock_delimited_daily['Last_Price']
                                                    - stock_delimited_daily['Open_Price']) / stock_delimited_daily['Open_Price']) * 100

    # Also include mean volume
    stock_delimited_daily['Mean_Volume'] = stock_data.groupby(
        [pd.Grouper(freq="D"), 'Ticker'])['latestVolume'].mean()

    # Classification Labels
    stock_delimited_daily['Price_Change'] = np.where(
        stock_delimited_daily['Price_Percent_Change'] >= 0, 1, 0)
    stock_delimited_daily['Open_Price_Change'] = np.where(
        stock_delimited_daily['Price_Percent_Open'] >= 0, 1, 0)

    # Rename the Index
    stock_delimited_daily = stock_delimited_daily.reindex(
        stock_delimited_daily.index.rename(['Time', 'Company']))
    return stock_delimited_daily


######################### Combine Data Frames ##############################
twitter_delimited_daily = create_twitter_data()
stock_delimited_daily = create_stock_data()
daily_df = pd.concat([twitter_delimited_daily, stock_delimited_daily], axis=1, join='inner')

# To flatten after combined everything.
daily_df.reset_index(inplace=True)

# Clean the Tweets
p.set_options(p.OPT.URL, p.OPT.EMOJI, p.OPT.MENTION, p.OPT.RESERVED, p.OPT.EMOJI, p.OPT.HASHTAG)


def preprocess_tweet(tweet):
    return p.clean(tweet)


# Clean the tweets, by removing special characters
daily_df['Clean_text'] = daily_df['text'].apply(lambda x: preprocess_tweet(x))

# Split Between Outcome and Features
features = daily_df[['Number_of_Tweets', 'Number_of_Users', 'Mean_Volume', 'Clean_text']]
classification_price = daily_df['Price_Change']

# Data Selector class to handle feature union


class DataSelector(BaseEstimator, TransformerMixin):
    def __init__(self, key):
        self.key = key

    def fit(self, x, y=None):
        return self

    def transform(self, features):
        if self.key == 'text':
            return features['Clean_text']
        else:
            return features.loc[:, features.columns != 'Clean_text']


# Split the Data to avoid Leakage
# splitting into training and test sets
X_train, X_test, y_train, y_test = train_test_split(features, classification_price, test_size=0.2)

# Create lemmatizer using spacy
lemmatizer = spacy.lang.en.English()

# Define Model
lr_model = LogisticRegression(n_jobs=5, penalty='l2',
                              class_weight='balanced', solver='newton-cg', C=10)

# Define custom Tokenizer


def custom_tokenizer(doc):
    tokens = lemmatizer(doc)
    return([token.lemma_ for token in tokens if not token.is_punct])


# Define Vectorizer
vectorizer = TfidfVectorizer(tokenizer=custom_tokenizer, stop_words='english',
                             lowercase=True, use_idf=True, max_df=2,
                             min_df=2, norm='l2', smooth_idf=True, ngram_range=(1, 2))

# Define Pipeline and Feature Union
pipeline = Pipeline([
    # Use Feature Union to combine features from the Tweet and other features gathered
    ('union', FeatureUnion(
        transformer_list=[
            # Pipeline for text
            ('tweet', Pipeline([
                ('selector', DataSelector(key='text')),
                ('vectidf', vectorizer),
                ('svd', TruncatedSVD(1000)),
                ('norm', Normalizer(copy=False))

            ])),

            # Pipeline for getting other features
            ('other', Pipeline([
                ('seclector', DataSelector(key='other'))
            ])),
        ],
        # weight components in FeatureUnion
        transformer_weights={'tweet': 0.8, 'other': 0.2},

    )),
    # Use Logistic Regression Classifier
    ('lr', lr_model)
])

print('Train the model')
# Fit the grid
pipeline.fit(X_train, y_train)

# Predictions
# AUROC Score
prediction_proba = pipeline.predict_proba(X_test)
prediction_proba = [p[1] for p in prediction_proba]
auc = roc_auc_score(y_test, prediction_proba)
print(auc)

#### Train final model on the full dataset #####

start_time = time.time()

# Create lemmatizer using spacy
lemmatizer = spacy.lang.en.English()

# Define Model
lr_model = LogisticRegression(n_jobs=5, penalty='l2',
                              class_weight='balanced', solver='newton-cg', C=10)

# Define custom Tokenizer


def custom_tokenizer(doc):
    tokens = lemmatizer(doc)
    return([token.lemma_ for token in tokens if not token.is_punct])


# Define Vectorizer
vectorizer = TfidfVectorizer(tokenizer=custom_tokenizer, stop_words='english',
                             lowercase=True, use_idf=True, max_df=2,
                             min_df=2, norm='l2', smooth_idf=True, ngram_range=(1, 2))

# Define Pipeline and Feature Union
model = Pipeline([
    # Use Feature Union to combine features from the Tweet and other features gathered
    ('union', FeatureUnion(
        transformer_list=[
            # Pipeline for text
            ('tweet', Pipeline([
                ('selector', DataSelector(key='text')),
                ('vectidf', vectorizer),
                ('svd', TruncatedSVD(1000)),
                ('norm', Normalizer(copy=False))

            ])),

            # Pipeline for getting other features
            ('other', Pipeline([
                ('seclector', DataSelector(key='other'))
            ])),
        ],
        # weight components in FeatureUnion
        transformer_weights={'tweet': 0.8, 'other': 0.2},

    )),
    # Use Logistic Regression Classifier
    ('lr', lr_model)
])


# Fit the grid
model.fit(features, classification_price)

build_time = time.time() - start_time

############## Log to Database ##############
version = str(int(time.time()))
print('Log to database')
database_log('Daily_Stock_Prediction', version, float(auc), float(build_time))


############# Serialize the model ############
print('Serialize Model')
# Create Model Name
name = 'Daily_Stock_Prediction_' + version + '.pk'
latest = 'Daily_Stock_Prediction_latest.pk'

with open('./Models/' + name, 'wb') as file:
    pickle.dump(model, file)

with open('./Models/' + latest, 'wb') as file:
    pickle.dump(model, file)

########### Upload to S3 #########################

AWS_ACCESS_KEY_ID = os.environ['AWS_ACCESS_KEY_ID']
AWS_ACCESS_KEY_SECRET = os.environ['AWS_SECRET_ACCESS_KEY']


def upload_files(path):
    session = boto3.Session(
        aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],

    )
    s3 = session.resource('s3')
    bucket = s3.Bucket('brandyn-twitter-sentiment-analysis')

    for subdir, dirs, files in os.walk(path):
        for file in files:
            full_path = os.path.join(subdir, file)
            with open(full_path, 'rb') as data:
                bucket.put_object(Key=full_path, Body=data)


upload_files('Models')
