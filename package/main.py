from setup import *
from module import *
import requests # pip install
import json
import sched,time



def main():
    # get last treatment bg check date
    try:
        ns_last_bgcheck_date = get_last_treatment_bgcheck_date(ns_header)
        print("Last treatment BG Check date:", ns_last_bgcheck_date)
    except Exception as error:
            print("Error requesting from Nightscout:", error)

    # get Zoetis Alphatrak data
    try:
        at_data = get_at_entries(at_header,at_body)
        if at_data["StatusCode"] == 200:
            print("Alphatrak data received.")
    except Exception as error:
        print("Error requesting from Zoetis:", error)

    # process Alphatrak data and upload to Nightscout
    try:
        print ("Processing data...")
        process_at_json_data(at_data,ns_last_bgcheck_date)
    except Exception as error:
        print("Error reading direction:", error)

    # add task to scheduler
    scheduler.enter(uploader_interval*60, 1, main)

# scheduler to run periodically
scheduler = sched.scheduler(time.time, time.sleep)
scheduler.enter(0, 1, main)
scheduler.run()