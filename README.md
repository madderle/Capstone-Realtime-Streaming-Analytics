# Capstone-Realtime-Streaming-Analytics

Use Twitter to make stock predictions.

#### Team Members: Brandyn Adderley


Numerous companies are interested in using microblogging as a way to predict in real time how stock prices are going to move. At no other time in human history did investors have access to the real time thoughts and voices of the masses. The theory is if investors had a good sense of how customers felt about a particular company at any given time would give insight to how the “market” values the company and thus the price and volume of the stocks.

Even beyond the idea of analyzing tweets in real time, the idea of accessing real time information and using that to make decisions is the future. There is a diminishing value of data as time progresses. Insights are indeed perishable. But if you have the ability to combine old and recent data, that's even more valuable.


The goal of this project is twofold:
1. Set Up a production ready analytics system using AWS.
2. Use sentiment analysis of tweet to predict stock prices.

## Application Features
1. Data Sources turn on and off with the start and end of the market day.
2. Twitter Data Source filters on Ticker Symbols.
3. Feature Flags implemented to easily turn on/off writing to Kinesis streams and writing to Mongo DB.
4. Auto MongoDB backups.
5. Event and Error Logging.
6. Tweet and Stock Price count Logging.
7. Dedicated container for Data Analysis.



## Architecture

The overall architecture is shown in this image:
![Overall](../master/Documentation/Images/Architecture_Overall.png)

EC2 is hosting the dockerized production system that pushes data to Kinesis via the Boto3 library and a Mongo database.

The EC2 services is shown in this image:
![EC2](../master/Documentation/Images/Architecture_EC2.png)

There are several services running:
1. Stocks: This service is responsible for fetching Live stock data from IEX.
2. Twitter: This service is responsible for fetching tweets from the Twitter API.
3. Manager: This service is responsible for controlling when to turn on fetching when the market is open.
4. Redis: its the mechanism the Stock and Twitter services use to pass information to the Manager service.
5. Log: this service is used to log events from the other services.
6. Data Store: This service is used as a backup to sending data to Kinesis. Its a way to quickly gather data without having to pay the transfer costs of Kinesis.
7. Analysis: this service is used to analyze the data from the Data Store. Its being used to validate different machine learning models to deploy in production.
8. Backup: This service performs daily backups of the MongoDB and uploads to S3.


The full system diagram is shown in this image:
![Full](../master/Documentation/Images/Architecture_Full.png)
