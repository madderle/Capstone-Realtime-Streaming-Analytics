FROM continuumio/anaconda3

#Run an update
RUN apt-get update

#Create a user ds
RUN adduser -D -S -h /home/ds -s /bin/ash ds

#install neccessary packages
RUN pip install --upgrade pip
RUN pip install jupyterlab boto3 gensim tweet-preprocessor redis mysql-connector==2.1.4 sqlalchemy pymongo
RUN conda update conda
RUN conda install nltk
RUN conda install spacy -y
RUN conda install -c conda-forge xgboost
RUN python -m spacy download 'en'
RUN python -m nltk.downloader -d /usr/local/share/nltk_data all


#Set Variables
ENV HOME=/home/ds
ENV SHELL=/bin/bash
ENV USER=ds
VOLUME /home/ds
WORKDIR /home/ds

#Startup the Jupyter notebook when this runs.
CMD jupyter lab --no-browser --port 7799 --ip='*' --allow-root --NotebookApp.iopub_data_rate_limit=10000000
