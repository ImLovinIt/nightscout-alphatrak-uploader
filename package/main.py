from setup import *
from module import *
import json
import sched,time


def main():
    try:
        # get last treatment bg check date. 0 means upload everything Alphatrak
        # still holds, which is what a first run should do.
        ns_last_bgcheck_date = 0
        try:
            ns_last_bgcheck_date = get_last_treatment_bgcheck_date(ns_header)
        except Exception as error:
            print("Error requesting from Nightscout:", error)

        # get Zoetis Alphatrak data
        at_data = None
        try:
            at_data = get_at_entries(at_header, return_at_body())
        except Exception as error:
            print("Error requesting from Zoetis:", error)

        # process Alphatrak data and upload to Nightscout
        if at_data is None:
            print("Skipping upload. No usable Zoetis response this run.")
        else:
            try:
                process_at_json_data(at_data,ns_last_bgcheck_date)
            except Exception as error:
                print("Error processing glucose data:", error)

    except Exception as error:
        print("Unexpected error during run:", error)

    finally:
        # always re-arm the scheduler, otherwise one bad run ends the process.
        # Readings are taken by hand with no publishing cadence to line up with,
        # so a plain fixed interval is enough here.
        scheduler.enter(uploader_interval*60, 1, main)

# scheduler to run periodically
scheduler = sched.scheduler(time.time, time.sleep)

if __name__ == "__main__":
    scheduler.enter(0, 1, main)
    scheduler.run()
