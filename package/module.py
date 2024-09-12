from setup import *
import requests
import pprint
import json
import datetime

def convert_mmoll_to_mgdl(x):
    return round(x*ns_unit_convert)

def convert_mgdl_to_mmoll(x):
    return round(x/ns_unit_convert, 1)

# NS api v1
# get last treatment Bg Check date.
def get_last_treatment_bgcheck_date(header):
    r=requests.get(ns_url+"api/v1/treatments.json?find[eventType][$eq]=BG Check&find[enteredBy][$eq]="+ns_uploder, headers=header)
    try:
        data = r.json()
        if data == []:
            print("Nightscout request", r.status_code , r.reason)
            print("no data")
            return "0"
        else:
            print("Nightscout request", r.status_code , r.reason)
            print("Last treatment BG Check date" , data[0]["created_at"])
            return data[0]["created_at"]
    except requests.JSONDecodeError:
        content_type = r.headers.get('Content-Type')
        print("Failed. Content Type " + content_type)

# post treatment Bg Check
def ns_post_treatment_bgcheck(entries_json,header,n): #entries tpye = a list of dicts
    r=requests.post(ns_url+"api/v1/treatments", headers = header, json = entries_json)
    if r.status_code == 200:
        print("Nightscout POST request", r.status_code , r.reason)
        print(n, "entries uploaded")
    else:
        print("Nightscout POST request", r.status_code , r.reason, r.text)

# ======================================================
# get Alphatrak data
def get_at_entries(header,body):
    r=requests.post(at_url, headers=header, data=json.dumps(body))
    try:
        data = r.json()
        print("Zoetis Response Status:" , r.status_code , r.reason)
        # pprint.pprint(r.json(), compact=True)
    except requests.JSONDecodeError:
        content_type = r.headers.get('Content-Type')
        print("Failed. Content Type " , content_type)
    return data

# process Alphatrak data
def process_at_json_data(data,last_date):
    count = 0
    list_dict = []
    try:
        if type(data["ResponseData"]["PetActivity"]["BloodGlucose"]) == list:
            for i in data["ResponseData"]["PetActivity"]["BloodGlucose"]:
                count,list_dict = process_at_json_data_prepare_json(i,last_date,count,list_dict)
        elif type(data["ResponseData"]["PetActivity"]["BloodGlucose"]) == dict:
            count,list_dict = process_at_json_data_prepare_json(data["ResponseData"]["PetActivity"]["BloodGlucose"],last_date,count,list_dict)
        else:
            print(type(data["ResponseData"]["PetActivity"]["BloodGlucose"]), " recieved. Check API content.")
    except Exception as error:
        print("Error reading BloodGlucose:", error)
    # finally:
    #     print(str(count) + " entries read")
    if len(list_dict) > 0:
        upload_json = json.loads(json.dumps(list_dict))
        ns_post_treatment_bgcheck(upload_json,ns_header,len(list_dict))
    else:
        print("No new entry found.")

def process_at_json_data_prepare_json(item,last_date,count,list_dict): # item type = dict
    try:
        if uploader_max_entries !=0 and count >= uploader_max_entries:
            return
        if item["GlucoseEntryDateTime"]>last_date or uploader_all_data==True:
            entry_dict = {
                "eventType": "BG Check",
                "created_at": datetime.datetime.fromisoformat(item["GlucoseEntryDateTime"]).isoformat(timespec="milliseconds")+"Z",
                "glucose": item["GlucoseLevel"],
                "glucoseType": "Finger",
                "units": "mmol",
                "enteredBy": ns_uploder,
            }
            list_dict.append(entry_dict)
            count +=1
        return count,list_dict
    except Exception as error:
        print("Error processing BloodGlucose:", error)
