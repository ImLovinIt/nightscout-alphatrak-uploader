import datetime
import os
import sys

# Initilisation for local python script
# at_token = ""
# at_petid = 0
# ns_url = ""
# ns_api_secret= "" #api_secret
# uploader_interval = 30 #mins
# uploader_max_entries = 0 # 0 to disable.
# uploader_all_data = False
# retries = 10
# timeout = 10

# Environment variable readers.
# A bare "except" here would also swallow KeyboardInterrupt and SystemExit, and
# str/int/bool each need different handling, so read them explicitly instead.
def env_str(name, default=None, required=False):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        if required:
            sys.exit(name + " required. Pass it as an Environment Variable.")
        return default
    return value


def env_int(name, default=None, required=False):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        if required:
            sys.exit(name + " required. Pass it as an Environment Variable.")
        return default
    try:
        return int(value)
    except ValueError:
        sys.exit(name + " must be a whole number. Got: " + value)


def env_bool(name, default=False):
    # bool("False") is True, so the string has to be compared, not cast.
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("true", "1", "yes", "on")


# Initilisation for docker & ENV parameters overwrite
at_token = env_str('at_token', required=True)
at_petid = env_int('at_petid', required=True)
ns_url = env_str('ns_url', required=True)
ns_api_secret = env_str('ns_api_secret', required=True)

# Every Nightscout call concatenates a path straight onto ns_url, so a missing
# trailing slash turns https://host + api/v1/treatments into https://hostapi/v1/treatments
# and the whole run fails on DNS. Guarantee the separator here instead of trusting
# the variable, and strip stray whitespace while at it.
ns_url = ns_url.strip().rstrip("/")+"/"

# urllib3 cannot request a schemeless URL, and the failure it raises is not obvious,
# so say so plainly at startup. at_url is a constant below and needs no check.
if not ns_url.lower().startswith(("http://", "https://")):
    sys.exit("ns_url must start with http:// or https://. Got: " + ns_url)

uploader_interval = env_int('uploader_interval', 30)
uploader_max_entries = env_int('uploader_max_entries', 0)
uploader_all_data = env_bool('uploader_all_data', False)


# Vendor clock corrections.
#
# A meter keeps its own clock and it can be wrong. Readings already synced carry
# whatever it said at the time, so setting the device right fixes future readings
# and repairs none of the history. Correcting the timestamps directly in
# Nightscout does not hold either: the next run re-uploads the vendor's originals,
# and because the upsert keys on created_at the corrected copies sit alongside the
# wrong ones rather than replacing them. The correction therefore belongs here,
# reapplied on every run, so one timestamp per reading is the only thing
# Nightscout ever sees and repeated runs stay idempotent.
#
# Three variables, all or nothing:
#
#   at_clock_drift_minutes    signed. Positive for a meter running slow, that is
#                             one stamping readings earlier than they happened.
#   at_clock_drift_from       when the fault began.
#   at_clock_drift_fixed_at   when you corrected the device clock.
#
# Both dates are matched against the VENDOR's own uncorrected timestamp, never the
# corrected one, so the rule means the same thing on every run regardless of what
# has already been uploaded. The range includes from and excludes fixed_at.
#
# Naive values are read as UTC. An offset is honoured, so a local wall clock can be
# pasted in as is, which is less error prone than converting by hand:
#
#   at_clock_drift_minutes=488
#   at_clock_drift_from=2026-03-21
#   at_clock_drift_fixed_at=2026-08-10T21:00+10:00
#
# fixed_at is the right boundary and is provably so. A reading taken before the
# fix, at true time T, is stamped T minus the drift, which is below T and so below
# fixed_at, and is corrected. A reading taken after the fix is stamped at its true
# time, at or above fixed_at, and is left alone. That holds however many readings
# fall either side.
#
# There is no switch to turn this off once the history is right, and there must not
# be. The vendor keeps serving the original wrong timestamps forever, so disabling
# the rule would write them straight back on the next full upload. The rule stays
# in the configuration permanently. What is bounded is the window, not its life.
def env_utc_ms(name):
    raw = env_str(name)
    if raw is None:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw.strip())
    except ValueError:
        sys.exit(name + " must be an ISO date or datetime, for example 2026-03-21 "
                 "or 2026-08-10T21:00+10:00. Got: " + raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return round(parsed.timestamp()*1000)


_drift_minutes = env_int('at_clock_drift_minutes')
_drift_from = env_utc_ms('at_clock_drift_from')
_drift_fixed_at = env_utc_ms('at_clock_drift_fixed_at')

# A half configured correction is worse than none, so require the set or refuse.
_drift_given = [n for n, v in (("at_clock_drift_minutes", _drift_minutes),
                               ("at_clock_drift_from", _drift_from),
                               ("at_clock_drift_fixed_at", _drift_fixed_at))
                if v is not None]
if _drift_given and len(_drift_given) < 3:
    sys.exit("A clock drift correction needs all three of at_clock_drift_minutes, "
             "at_clock_drift_from and at_clock_drift_fixed_at. Only these were set: "
             + ", ".join(_drift_given))

at_clock_drift = None
if len(_drift_given) == 3:
    if _drift_minutes == 0:
        sys.exit("at_clock_drift_minutes is 0, which would correct nothing. Remove "
                 "all three variables instead, or set the real drift.")
    if _drift_from >= _drift_fixed_at:
        sys.exit("at_clock_drift_from must be before at_clock_drift_fixed_at.")
    # Whoever types a drift has already fixed the device, so the fix is in the past.
    # A future value means either the clock is not fixed yet, in which case the
    # correction should not be configured, or a local time was written without its
    # offset and has been read as UTC, which is the likeliest typo of the three.
    _now_ms = round(datetime.datetime.now(datetime.timezone.utc).timestamp()*1000)
    if _drift_fixed_at > _now_ms:
        sys.exit("at_clock_drift_fixed_at is in the future. Fix the device clock "
                 "first, then set this to the moment you did it. If you meant a "
                 "local time, include the offset, for example "
                 "2026-08-10T21:00+10:00 rather than 2026-08-10T21:00.")
    at_clock_drift = (_drift_from, _drift_fixed_at, _drift_minutes*60000)

retries = env_int('retries', 10)
timeout = env_int('timeout', 10)

if uploader_interval <= 0:
    sys.exit("uploader_interval must be greater than 0.")

# Say it out loud at startup. Rewriting the timestamp on a medical record is not
# something that should ever happen quietly, and this is the one place a reader of
# the logs can see the rule that is in force.
if at_clock_drift is not None:
    def _utc_text(ms):
        return (datetime.datetime.fromtimestamp(ms/1000, datetime.timezone.utc)
                .isoformat(timespec="minutes").replace("+00:00", "Z"))
    print("Meter clock correction active. Readings the meter stamped from",
          _utc_text(at_clock_drift[0]), "up to but not including",
          _utc_text(at_clock_drift[1]), "are shifted by",
          str(round(at_clock_drift[2]/60000)),
          "minute(s). Everything outside that window is untouched.")
    # A battery change can leave a clock years out, so a large drift is not wrong
    # in itself. A tenfold typo is the thing worth a second look.
    if abs(at_clock_drift[2]) > 48*3600000:
        print("   Note: that drift is over 48 hours. Correct if the device clock was",
              "reset, worth re-reading if it was meant to be a smaller number.")

#API URL
at_url = "https://alphatrakapi.zoetis.com/api/GetPetActivityByDateWiseList"

# uploader initialisation
# This string is written to enteredBy on every treatment and is matched on when
# reading the last one back, so changing it orphans everything already posted.
ns_uploder = "nightscout-alphatrak-uploader"
ns_unit_convert = 18.018

# header initialisation
ns_header = {"api-secret": ns_api_secret,
             "User-Agent": ns_uploder,
             "Content-Type": "application/json",
             "Accept":"application/json",
             }

at_header = {"Authorization": "Bearer "+at_token,
             "User-Agent": ns_uploder,
             "Content-Type": "application/json",
             "Accept":"application/json",
             }
