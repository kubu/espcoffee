from time import sleep
from collections import deque
from config import *
from sys import argv
import paho.mqtt.client as mqtt

# timer boundaries (seconds)
BREW_START = 35                 # measured at 1100W
BLOOM_TIME = 45                 # sleep cycle during blooming
BLOOM_START = 15                # after first water drip
TOGGLE_TIME = 25                # "on" time cycle
TOGGLE_OFF_TIME = 7             # seconds during TOGGLE_TIME when heater is off, for slower coffee extraction
HEAT_SAFE_LIMIT = 420           # 7 minutes, turns off when reached during normal brew (full heater power)
KEEP_WARM_SAFE_LIMIT = 1800     # 30 minutes, turns off when reached during "keep warm" heater function

# other
KEEP_WARM_WATTAGE = 80      # threshold in Watts indicating that heater is on keep_warm setting
SENSOR_READ_INTERVAL = 6    # set on ESP device (seconds)

# queue with power measurements
power_reports = deque('0', maxlen=10)

# timer
timer = 0

'''
MQTT callbacks
'''


def on_log(client, userdata, level, buf):
    if (log_switch()):
        print ("\tlog: " + buf)


def on_connect(client, userdata, flags, rc):
    if rc:
        print ("Connection NOK: ", rc)
    else:
        print ("Connection OK")


def on_disconnect(client, userdata, flags, rc=0):
    print ("Disconnected, code: ", rc)


def on_message(client, userdata, msg):
    m_decode = str(msg.payload.decode())
    print ("Message: ", m_decode)


def on_message_power(client, userdata, msg):
    payload = int(msg.payload.decode())
    #print ("Received power raport: ", payload)
    power_reports.append(payload)


'''
logs configuration and flow control
'''


def enable_logs(switch):
    f = open("log_switch", "w")
    print ("Logs enabled:", switch)
    f.write(str(switch))
    f.close()


def log_switch():
    f = open("log_switch", "r")
    logs_state = int(f.read())
    f.close()
    return logs_state


def flow_control():
    # check if any arguments passed, if not, default is brew
    if len(argv) > 1:
        arg = argv[1]
    else:
        arg = "brew"

    # before connecting, check if there's need to switch logs on/off
    if arg == "log_on":
        enable_logs(1)
        return
    elif arg == "log_off":
        enable_logs(0)
        return

    print ("Connecting to broker... ", broker)
    client.connect(broker, port=port)
    # main mqtt loop
    client.loop_start()
    # subscribe for power measurements
    client.subscribe("espcoffee/power")
    # wait for acks
    sleep(1)

    # connection done, select a mode
    if arg == "brew":
        brew()
    elif arg == "brew_keep_warm":
        brew(True)
    elif arg == "turn_off":
        toggle_heater(0)
    elif arg == "turn_on":
        toggle_heater(1)

    # done, disconnect
    client.loop_stop()
    client.disconnect()


'''
machine handling
'''


def toggle_heater(action="toggle"):
    global timer
    if action == "pause":
        print ("Heater: toggling off", timer)
        client.publish("espcoffee/relay/0/set", 0)
        sleep(TOGGLE_OFF_TIME)
        timer += TOGGLE_OFF_TIME
        print ("Heater: toggling on", timer)
        client.publish("espcoffee/relay/0/set", 1)
    else:
        client.publish("espcoffee/relay/0/set", action)


def keep_warm():
    timer_warm = KEEP_WARM_SAFE_LIMIT
    while timer_warm:
        if (timer % 60 == 0):
            print (f"Keeping warm for {timer_warm} seconds... ")
        sleep(1)
        timer_warm -= 1
    # keep warm limit reached, turning off heater
    print(f"Kept warm for {KEEP_WARM_SAFE_LIMIT} seconds, finished.")
    toggle_heater(0)


def print_debug(timer):
    if (timer % SENSOR_READ_INTERVAL == 0):
        print (f"Power: {power_reports[-1]}W, timer: {timer}s")


def brew(keepWarm=False):
    # start brewing
    toggle_heater(1)

    blooming_done = False
    global timer

    while True:

        # increment timer
        print_debug(timer)
        sleep(1)
        timer += 1

        # turn heater off when safe limit reached
        if (timer > HEAT_SAFE_LIMIT):
            print (f"Safe limit reached, time elapsed: {timer}. ")
            toggle_heater(0)
            return

        # turn heater off for coffee blooming
        if not blooming_done and (timer == BREW_START + BLOOM_START):
            print (f"Blooming started, time elapsed: {timer}")
            toggle_heater(0)
        # turn heater on when blooming is finished
        elif (timer == BREW_START + BLOOM_START + BLOOM_TIME):
            print (f"Blooming finished, time elapsed: {timer}")
            toggle_heater(1)
            blooming_done = True

        # toggle heater every TOGGLE_TIME
        if blooming_done and timer % TOGGLE_TIME == 0:
            toggle_heater("pause")

        # last power report indicates the state of machine
        if 0 < power_reports[-1] < KEEP_WARM_WATTAGE:
            if timer < BREW_START + BLOOM_START:
                # keep warm phase reached too fast, probably no water
                print ("No water. ")
                toggle_heater(0)
                return
            if keepWarm:
                # brewing is done, but keep heater on for keep warm phase
                print ("Keep warm active. ")
                keep_warm()
            else:
                # brewing is done, turning off heater
                print (f"Brewing finished, time elapsed {timer}. ")
                toggle_heater(0)
            return


# configure broker
client = mqtt.Client("python_coffee_controller")
client.username_pw_set(username=username, password=password)

# register callback functions
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_log = on_log
client.on_message = on_message
client.message_callback_add("espcoffee/power", on_message_power)

# choose mode of operation
flow_control()
