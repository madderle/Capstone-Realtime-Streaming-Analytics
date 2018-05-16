FROM jupyter/pyspark-notebook

#Create a user ds
RUN adduser -D -S -h /home/ds -s /bin/ash ds

#install neccessary packages
RUN pip install jupyterlab boto3 pymongo tweet-preprocessor redis

#Set Variables
ENV HOME=/home/ds
ENV SHELL=/bin/bash
ENV USER=ds
VOLUME /home/ds
WORKDIR /home/ds


#Startup the Jupyter notebook when this runs.
CMD jupyter lab --no-browser --port 7788 --ip='*' --allow-root --NotebookApp.iopub_data_rate_limit=10000000
