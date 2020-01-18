from calendar import calendar
from datetime import datetime
import calendar
import time

import requests
from datadog import initialize, api
import json
from phue import Bridge
from enum import Enum


class BulbColour(Enum):
    RED = 1
    ORANGE = 2
    GREEN = 3


def discover_ip():
    response = requests.get('https://discovery.meethue.com')

    # process response

    if response and response.status_code == 200:
        data = response.json()

        if 'internalipaddress' in data[0]:
            return data[0]['internalipaddress']
    return None


def is_during_active_hours(options):

    # Check if the flag for alerting only during active hours is set. If its set to 0, just return True
    # as user wants alerted 24/7

    if options['alert_active_hours_only'] == 0:
        return True

    # Get the current epoch time
    current_epoch = time.time()
    current_date = str(datetime.date(datetime.now()))

    start_active_hours_epoch = calendar.timegm(time.strptime(current_date + ' ' + options['start_active_hours'],
                                                             '%Y-%m-%d %H:%M'))
    end_active_hours_epoch = calendar.timegm(time.strptime(current_date + ' ' + options['end_active_hours'],
                                                           '%Y-%m-%d %H:%M'))

    if current_epoch >= start_active_hours_epoch and current_epoch <= end_active_hours_epoch:
        return True
    else:
        return False


def flash_lights(bulb_colour):
    options = {
        'alert_active_hours_only': 1,
        'start_active_hours': '09:00',
        'end_active_hours': '22:00'
    }

    if not is_during_active_hours(options):
        print("Not during active hours so not flashing lights")
        # Return False to tell the main function there was no alert done so the config file
        # doesn't get updated. This allows that if the monitor is still active when it runs again
        # during active hours the bulbs are flashed
        return False

    print("Flashing lights as during active hours or active hours only alerting is disabled")

    lights = b.lights

    if bulb_colour == BulbColour.RED:
        hue = 64015
        saturation = 254
    elif bulb_colour == BulbColour.ORANGE:
        hue = 8382
        saturation = 252
    elif bulb_colour == BulbColour.GREEN:
        hue = 25652
        saturation = 254

    # Need to store the existing light settings so we can revert the lights back after flashing
    original_light_states = []
    # Get the colour light indexes so can update the hue and sat without receiving an error setting a non colour bulb
    colour_light_ids = []

    # Need a list of all light id so can control all lights on/off state together
    all_light_ids = []

    for light in lights:
        light_state = {}
        light_state['id'] = light.light_id
        light_state['name'] = light.name
        light_state['on'] = light.on
        light_state['brightness'] = light.brightness
        if light.type == 'Extended color light':
            colour_light_ids.append(light.light_id)
            light_state['hue'] = light.hue
            light_state['sat'] = light.saturation
            light_state['xy'] = light.xy

        original_light_states.append(light_state)
        all_light_ids.append(light.light_id)

    # Flash each light on an off every 1 second for 3 seconds
    bulb_on_state = 40
    b.set_light(all_light_ids, 'on', True)
    # Set the bulbs to the alert colour
    b.set_light(colour_light_ids, 'hue', hue)
    b.set_light(colour_light_ids, 'sat', saturation)
    time.sleep(0.3)
    for i in range(8):
        b.set_light(all_light_ids, 'bri', bulb_on_state)
        #  Set bulb state to opposite of current state
        if bulb_on_state == 40:
            bulb_on_state = 254
        else:
            bulb_on_state = 40

        time.sleep(0.3)

    # Now restore the states of the bulbs
    # Because each bulb might and most likely different settings each bulb has to be individually updated
    for light in lights:
        light_id = light.light_id

        # Loop over the original states looking for this id and if found update the buld to the correct settings
        for state in original_light_states:
            if state['id'] == light_id:
                light.on = state['on']
                if state['on']:
                    light.brightness = state['brightness']
                    if light.type == 'Extended color light':
                        light.hue = state['hue']
                        light.saturation = state['sat']
                        light.xy = state['xy']
                break
    # Return true so the main method knows the lights were flashed so user was updated
    # therefore update the config file so they don't get alerted again
    return True


hue_bridge_ip = discover_ip()
print("Hue Bridge IP: " + hue_bridge_ip)
if hue_bridge_ip is None:
    print("The IP address of Philips Hue Bridge could not be found. Please provide the IP address manually")
    exit(0)

b = Bridge(hue_bridge_ip)
b.connect()

dd_options = {
    'api_key': '',
    'app_key': ''
}

# Check if the count file exists if not create a default one
try:
    f = open("alert_count.json")
except IOError:
    counts_json = '{"warn_count": 0, "alert_count": 0}'
    f = open("alert_count.json", "w")
    f.write(counts_json)
    f.close()

initialize(**dd_options)

monitors = api.Monitor.get_all()

alert_count = 0
warn_count = 0
ok_count = 0

for monitor in monitors:
    monitorName = monitor['name']
    monitorStatus = monitor['overall_state']
    if monitorStatus == 'OK':
        ok_count += 1
    elif monitorStatus == 'Alert':
        alert_count += 1
    elif monitorStatus == 'Warn':
        warn_count += 1

    print('Monitor Name: ' + monitorName + " Status: " + monitorStatus)

print("OK Count: " + str(ok_count))
print("Warn Count: " + str(warn_count))
print("Alert Count: " + str(alert_count))

with open('alert_count.json') as json_file:
    counts_json = json.load(json_file)

file_warn_counts = counts_json['warn_count']
file_alert_counts = counts_json['alert_count']

were_lights_updated = False

if warn_count > 0 or alert_count > 0:
    # Check the alert_count.json file, if the counts in the file are 0, not previously alerted so flash the lights

    if file_warn_counts == 0 and file_alert_counts == 0:
        # Need to flash the lights - check what the wost alert level is
        if alert_count > 0:
            # Need to flash the lights red
            print("Flashing philips hue to be red")
            were_lights_updated = flash_lights(BulbColour.RED)
        elif warn_count > 0:
            # Need to flash the lights orange
            print("Flashing philips hue to be orange")
            were_lights_updated = flash_lights(BulbColour.ORANGE)
    elif file_warn_counts > 0 or file_alert_counts > 0:
        if file_alert_counts > 0 and alert_count == 0 and warn_count > 0:
            # If here, then previously alerted red but red alert recovered and now on warning
            # so flash philips hue orange instead
            print("alert recovered so flashing orange instead")
            were_lights_updated = flash_lights(BulbColour.ORANGE)
        elif (file_alert_counts > 0 or file_warn_counts) and (alert_count > 0 or warn_count > 0):
            # The file has some alerts and warning counts and there are still current alert and warning
            # counts so don't do anything with the lights
            print("no alerts and warnings recovered so not flashing the lights")
    else:
        print("Previously alerted and alerts are still happening so don't do anything with lights")

else:
    # There are no warnings and no errors check the file counts, if any are over 0, the monitors are therefore
    # recovered so flash green
    if file_alert_counts > 0 or file_warn_counts > 0:
        # The file did have an alert count the last time it run, so flash the lights green
        print("Everything recovered so flash lights green")
        were_lights_updated = flash_lights(BulbColour.GREEN)

if were_lights_updated:
    # Save a JSON file of the current counts. This will be used so that if the file already shows the counts for non OK
    # are > 1 so don't inadvertently keep flashing the users lights
    counts_json = '{"warn_count": ' + str(warn_count) + ', "alert_count":' + str(alert_count) + '}'
    f = open("alert_count.json", "w")
    f.write(counts_json)
    f.close()

exit(0)