# wifi-cluster.py

import sys
from os import popen

from subprocess import call

from mininet.cluster.net import MininetCluster
from mininet.cluster.cli import ClusterCLI
from mininet.log import setLogLevel, info
from mininet.wifi import *
from mininet.opennet import *

AP = 1
STA = 2
ADHOC = 2
CPU = 1
IP = ""

def emulation ():

    # Use MininetCluster for cluster emulation of hosts and switches
    servers = ['master']
    # Do not use 127.0.0.1
    serverIP = {'master': IP}
    net = MininetCluster (controller=None, user='root', servers=servers, serverIP=serverIP)

    # Add OpenFlow Switches (OVS)
    info ("*** Add OFS\n")
    rootSwitch = net.addSwitch ("sw0", failMode='standalone', user='root', server='master', serverIP=IP)

    wifiList = []

    stationIP = {"h1": "10.0.0.1", "h2": "10.0.0.2"}
    adhocIP = {"adhoc1": "10.0.1.1", "adhoc2": "10.0.1.2", "adhoc3": "10.0.1.3"}

    # Create one WIFI object for each available CPU
    for c in range (0, CPU):

        LOG = "/tmp/ns-3-log-{0}.txt".format (c)

        # Reference mininet/wifi.py for more detail of WIFI class
        wifi = WIFI (enableQos=True, rootSwitch=rootSwitch, serverIp=IP)

        info ('*** Add Access Point on WIFI {0}\n'.format (c))
        for i in range (c * (AP / CPU) + 1, (c + 1) * (AP / CPU) + 1):
            name = "ap{0}".format (i)
            info (name + " ")
            sw = net.addSwitch (name, failMode='standalone', user='root', server='master', serverIP=IP)
            wifi.addAP (sw, channelNumber=1, ssid="opennet")
        info ('\n')

        info ('*** Add Station on WIFI {0}\n'.format (c))
        for i in range (c * (STA / CPU) + 1, (c + 1) * (STA / CPU) + 1):
            name = "h{0}".format (i)
            info (name + " ")
            # Station is combination of Mininet host and NS-3 node
            host = net.addHost (name, ip=stationIP[name], user='root', server='master', serverIP=IP)
            wifi.addSta (host, channelNumber=1, ssid="opennet")
        info ('\n')

        info ('*** Add Adhoc on WIFI {0}\n'.format (c))
        for i in range (c * (ADHOC / CPU) + 1, (c + 1) * (ADHOC / CPU) + 1):
            name = "adhoc{0}".format (i)
            info (name + " ")
            host = net.addHost (name, ip=adhocIP[name], user='root', server='master', serverIP=IP)
            wifi.addAdhoc (host)
            # For mobility
            # wifi.addAdhoc (host, mobilityType="ns3::ConstantVelocityMobilityModel", velocity=[0,0,0], position=[0,0,0])
        info ('\n')

        wifiList.append (wifi)

    info ('*** net.start ()\n')
    net.start ()

    info ('*** wifi.start ()\n')
    for wifi in wifiList:
        wifi.start ()

    ClusterCLI (net)

    for wifi in wifiList:
        wifi.stop ()
        wifi.clear ()
    net.stop ()

if __name__ == '__main__':

    IP = getIntfAddr ('eth0')

    setLogLevel ('info')
    emulation ()
