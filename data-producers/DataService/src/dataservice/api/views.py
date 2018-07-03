####################### Imports ###############################

# Django Imports
from django.shortcuts import render
from django.http import HttpResponse

# Data Building Imports
import numpy as np
import pandas as pd
import json
from pymongo import MongoClient
import pymongo
import os
import datetime


#################### Connect to MongoDB ####################
#Setup Mongo and create the database and collection
User = os.environ['MONGODB_USER']
password = os.environ['MONGODB_PASS']

client = MongoClient('db-data', username=User, password=password)
db = client['stock_tweets']

# #Grab references
twitter_coll_reference = db.twitter
iex_coll_reference = db.iex



#################### Common functions #####################

def create_tweet_datafame(dataframe):
    # Need to convert the created_at to a time stamp and set to index
    dataframe.index=pd.to_datetime(dataframe['created_at'])

    # Delimited the Company List into separate rows
    delimited_twitter_data=[]

    for item in dataframe.itertuples():
        for company in item[1]:
            twitter_dict={}
            twitter_dict['created_at']=item[0]
            twitter_dict['company']=company
            twitter_dict['text']=item[11]
            twitter_dict['user_followers_count']=item[12]
            twitter_dict['user_name']=item[13]
            twitter_dict['user_statuses_count']=item[15]
            delimited_twitter_data.append(twitter_dict)

    delimited_twitter_df = pd.DataFrame(delimited_twitter_data)
    delimited_twitter_df.set_index('created_at', inplace=True)

    # Create output data frame
    twitter_delimited = delimited_twitter_df.groupby('company').count()['text'].to_frame()
    twitter_delimited.columns = ['Number_of_Tweets']

    # Number of Users
    twitter_delimited['Number_of_Users'] = delimited_twitter_df.groupby('company')['user_name'].nunique()

    # Rename Index
    #twitter_delimited = twitter_delimited.reindex(twitter_delimited.index.rename(['Company']))
    return twitter_delimited


####################### Views #################################

# Today's tweets
today = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

def today_tweets(request):
    # Create Dataframe
    twitter_data = pd.DataFrame(list(twitter_coll_reference.find({
        'created_at': { '$gte': today }})))

    output = create_tweet_datafame(twitter_data)
    output_json = output.to_json()
    return HttpResponse(output_json)

# Window tweets

def window_tweets(request, minutes):
    # Create DataFrame
    window = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)
    twitter_data = pd.DataFrame(list(twitter_coll_reference.find({
        'created_at': { '$gte': window }})))

    output = create_tweet_datafame(twitter_data)
    output_json = output.to_json()
    return HttpResponse(output_json)
