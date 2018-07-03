FROM python:3.6.3-slim

#Update the image
RUN apt-get update


#Create a user ds
RUN adduser -D -S -h /home/ds -s /bin/ash ds

#install neccessary packages
RUN pip install pymongo  numpy pandas  redis jupyter mysql-connector==2.1.4 sqlalchemy django==2.0.7 djangorestframework==3.7 gunicorn==19.7.0

#Set Variables
ENV HOME=/home/ds
ENV SHELL=/bin/bash
ENV USER=ds
VOLUME /home/ds
WORKDIR /home/ds
