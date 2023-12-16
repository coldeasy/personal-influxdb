#!/usr/bin/python3
# Copyright 2022 Sam Steele
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import requests, sys, os, pytz
from datetime import datetime, date, timedelta
from config import *

POINTS = []


def fetch_data(category, type):
    try:
        response = requests.get(f'https://api.fitbit.com/1/user/-/{category}/{type}/date/today/1d.json', 
            headers={'Authorization': f'Bearer {FITBIT_ACCESS_TOKEN}', 'Accept-Language': FITBIT_LANGUAGE})
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.error("HTTP request failed: %s", err)
        sys.exit(1)

    data = response.json()
    logging.info(f"Got {type} from Fitbit")

    for day in data[category.replace('/', '-') + '-' + type]:
        POINTS.append({
                "measurement": type,
                "time": LOCAL_TIMEZONE.localize(datetime.fromisoformat(day['dateTime'])).astimezone(pytz.utc).isoformat(),
                "fields": {
                    "value": float(day['value'])
                }
            })


def fetch_heartrate(date):
    try:
        response = requests.get(f'https://api.fitbit.com/1/user/-/activities/heart/date/{date}/1d/1min.json', 
            headers={'Authorization': f'Bearer {FITBIT_ACCESS_TOKEN}', 'Accept-Language': FITBIT_LANGUAGE})
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.error("HTTP request failed: %s", err)
        sys.exit(1)

    data = response.json()
    logging.info("Got heartrates from Fitbit")

    for day in data['activities-heart']:
        if 'restingHeartRate' in day['value']:
            POINTS.append({
                    "measurement": "restingHeartRate",
                    "time": datetime.fromisoformat(day['dateTime']),
                    "fields": {
                        "value": float(day['value']['restingHeartRate'])
                    }
                })

        if 'heartRateZones' in day['value']:
            for zone in day['value']['heartRateZones']:
                if 'caloriesOut' in zone and 'min' in zone and 'max' in zone and 'minutes' in zone:
                    POINTS.append({
                            "measurement": "heartRateZones",
                            "time": datetime.fromisoformat(day['dateTime']),
                            "tags": {
                                "zone": zone['name']
                            },
                            "fields": {
                                "caloriesOut": float(zone['caloriesOut']),
                                "min": float(zone['min']),
                                "max": float(zone['max']),
                                "minutes": float(zone['minutes'])
                            }
                        })
                elif 'min' in zone and 'max' in zone and 'minutes' in zone:
                    POINTS.append({
                            "measurement": "heartRateZones",
                            "time": datetime.fromisoformat(day['dateTime']),
                            "tags": {
                                "zone": zone['name']
                            },
                            "fields": {
                                "min": float(zone['min']),
                                "max": float(zone['max']),
                                "minutes": float(zone['minutes'])
                            }
                        })

    if 'activities-heart-intraday' in data:
        for value in data['activities-heart-intraday']['dataset']:
            time = datetime.fromisoformat(date + "T" + value['time'])
            utc_time = LOCAL_TIMEZONE.localize(time).astimezone(pytz.utc).isoformat()
            POINTS.append({
                    "measurement": "heartrate",
                    "time": utc_time,
                    "fields": {
                        "value": float(value['value'])
                    }
                })


def process_levels(levels):
    for level in levels:
        type = level['level']
        if type == "asleep":
            type = "light"
        if type == "restless":
            type = "rem"
        if type == "awake":
            type = "wake"

        time = datetime.fromisoformat(level['dateTime'])
        utc_time = LOCAL_TIMEZONE.localize(time).astimezone(pytz.utc).isoformat()
        POINTS.append({
                "measurement": "sleep_levels",
                "time": utc_time,
                "fields": {
                    "seconds": int(level['seconds'])
                }
            })


def fetch_activities(date):
    try:
        response = requests.get('https://api.fitbit.com/1/user/-/activities/list.json',
            headers={'Authorization': f'Bearer {FITBIT_ACCESS_TOKEN}', 'Accept-Language': FITBIT_LANGUAGE},
            params={'beforeDate': date, 'sort':'desc', 'limit':10, 'offset':0})
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.error("HTTP request failed: %s", err)
        sys.exit(1)

    data = response.json()
    logging.info("Got activities from Fitbit")

    for activity in data['activities']:
        fields = {}

        if 'activeDuration' in activity:
            fields['activeDuration'] = int(activity['activeDuration'])
        if 'averageHeartRate' in activity:
            fields['averageHeartRate'] = int(activity['averageHeartRate'])
        if 'calories' in activity:
            fields['calories'] = int(activity['calories'])
        if 'duration' in activity:
            fields['duration'] = int(activity['duration'])
        if 'distance' in activity:
            fields['distance'] = float(activity['distance'])
            fields['distanceUnit'] = activity['distanceUnit']
        if 'pace' in activity:
            fields['pace'] = float(activity['pace'])
        if 'speed' in activity:
            fields['speed'] = float(activity['speed'])
        if 'elevationGain' in activity:
            fields['elevationGain'] = int(activity['elevationGain'])
        if 'steps' in activity:
            fields['steps'] = int(activity['steps'])

        for level in activity['activityLevel']:
            if level['name'] == 'sedentary':
                fields[level['name'] + "Minutes"] = int(level['minutes'])
            else:
                fields[level['name'] + "ActiveMinutes"] = int(level['minutes'])


        time = datetime.fromisoformat(activity['startTime'].strip("Z"))
        utc_time = time.astimezone(pytz.utc).isoformat()
        POINTS.append({
            "measurement": "activity",
            "time": utc_time,
            "tags": {
                "activityName": activity['activityName']
            },
            "fields": fields
        })


def _write_refresh_token(token):
    script_dir = os.path.dirname(__file__)
    refresh_token_path = os.path.join(script_dir, '.fitbit-refreshtoken')
    with open(refresh_token_path, "w+") as f:
        f.write(token)


def _get_refresh_token():
    script_dir = os.path.dirname(__file__)
    refresh_token_path = os.path.join(script_dir, '.fitbit-refreshtoken')
    token = None
    if os.path.isfile(refresh_token_path):
        with open(refresh_token_path, "r") as f:
            token = f.read().strip()
    elif 'FITBIT_REFRESH_TOKEN' in os.environ:
        token = os.environ['FITBIT_REFRESH_TOKEN'].strip()

    return token


def login():
    connect(FITBIT_DATABASE)
    global FITBIT_ACCESS_TOKEN

    if not FITBIT_ACCESS_TOKEN:
        refresh_token = _get_refresh_token()
        if refresh_token is not None:
            response = requests.post('https://api.fitbit.com/oauth2/token',
                data={
                    "client_id": FITBIT_CLIENT_ID,
                    "grant_type": "refresh_token",
                    "redirect_uri": FITBIT_REDIRECT_URI,
                    "refresh_token": refresh_token
                }, auth=(FITBIT_CLIENT_ID, FITBIT_CLIENT_SECRET))
        else:
            response = requests.post('https://api.fitbit.com/oauth2/token',
                data={
                    "client_id": FITBIT_CLIENT_ID,
                    "grant_type": "authorization_code",
                    "redirect_uri": FITBIT_REDIRECT_URI,
                    "code": FITBIT_INITIAL_CODE
                }, auth=(FITBIT_CLIENT_ID, FITBIT_CLIENT_SECRET))

        response.raise_for_status()

        json = response.json()
        FITBIT_ACCESS_TOKEN = json['access_token']
        refresh_token = json['refresh_token']
        _write_refresh_token(refresh_token)


def get_devices():
    try:
        response = requests.get('https://api.fitbit.com/1/user/-/devices.json',
            headers={'Authorization': f'Bearer {FITBIT_ACCESS_TOKEN}', 'Accept-Language': FITBIT_LANGUAGE})
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.error("HTTP request failed: %s", err)
        sys.exit(1)

    data = response.json()
    logging.info("Got devices from Fitbit")

    for device in data:
        POINTS.append({
            "measurement": "deviceBatteryLevel",
            "time": LOCAL_TIMEZONE.localize(datetime.fromisoformat(device['lastSyncTime'])).astimezone(pytz.utc).isoformat(),
            "tags": {
                "id": device['id'],
                "deviceVersion": device['deviceVersion'],
                "type": device['type'],
                "mac": device.get('mac'),
            },
            "fields": {
                "value": float(device['batteryLevel'])
            }
        })


def get_sleeps():
    end = date.today()
    start = end - timedelta(days=1)

    try:
        response = requests.get(f'https://api.fitbit.com/1.2/user/-/sleep/date/{start.isoformat()}/{end.isoformat()}.json',
            headers={'Authorization': f'Bearer {FITBIT_ACCESS_TOKEN}', 'Accept-Language': FITBIT_LANGUAGE})
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.error("HTTP request failed: %s", err)
        sys.exit(1)

    data = response.json()
    logging.info("Got sleep sessions from Fitbit")

    for day in data['sleep']:
        time = datetime.fromisoformat(day['startTime'])
        utc_time = LOCAL_TIMEZONE.localize(time).astimezone(pytz.utc).isoformat()
        if day['type'] == 'stages':
            POINTS.append({
                "measurement": "sleep",
                "time": utc_time,
                "fields": {
                    "duration": int(day['duration']),
                    "efficiency": int(day['efficiency']),
                    "is_main_sleep": bool(day['isMainSleep']),
                    "minutes_asleep": int(day['minutesAsleep']),
                    "minutes_awake": int(day['minutesAwake']),
                    "time_in_bed": int(day['timeInBed']),
                    "minutes_deep": int(day['levels']['summary']['deep']['minutes']),
                    "minutes_light": int(day['levels']['summary']['light']['minutes']),
                    "minutes_rem": int(day['levels']['summary']['rem']['minutes']),
                    "minutes_wake": int(day['levels']['summary']['wake']['minutes']),
                }
            })
        else:
            POINTS.append({
                "measurement": "sleep",
                "time": utc_time,
                "fields": {
                    "duration": int(day['duration']),
                    "efficiency": int(day['efficiency']),
                    "is_main_sleep": bool(day['isMainSleep']),
                    "minutes_asleep": int(day['minutesAsleep']),
                    "minutes_awake": int(day['minutesAwake']),
                    "time_in_bed": int(day['timeInBed']),
                    "minutes_deep": 0,
                    "minutes_light": int(day['levels']['summary']['asleep']['minutes']),
                    "minutes_rem": int(day['levels']['summary']['restless']['minutes']),
                    "minutes_wake": int(day['levels']['summary']['awake']['minutes']),
                }
            })
        if 'data' in day['levels']:
            process_levels(day['levels']['data'])
        if 'shortData' in day['levels']:
            process_levels(day['levels']['shortData'])


def main():
    login()
    get_devices()
    get_sleeps()
    fetch_data('activities', 'steps')
    fetch_data('activities', 'distance')
    fetch_data('activities', 'floors')
    fetch_data('activities', 'elevation')
    fetch_data('activities', 'distance')
    fetch_data('activities', 'minutesSedentary')
    fetch_data('activities', 'minutesLightlyActive')
    fetch_data('activities', 'minutesFairlyActive')
    fetch_data('activities', 'minutesVeryActive')
    fetch_data('activities', 'calories')
    fetch_data('activities', 'activityCalories')
    fetch_data('body', 'weight')
    fetch_data('body', 'fat')
    fetch_data('body', 'bmi')
    fetch_data('foods/log', 'water')
    fetch_data('foods/log', 'caloriesIn')
    fetch_heartrate(date.today().isoformat())
    fetch_activities((date.today() + timedelta(days=1)).isoformat())
    write_points(POINTS)


if __name__ == "__main__":
    if not FITBIT_CLIENT_ID or not FITBIT_CLIENT_SECRET:
        logging.error("FITBIT_CLIENT_ID or FITBIT_CLIENT_SECRET not set in config.py")
        sys.exit(1)
    main()
