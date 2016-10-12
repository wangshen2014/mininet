# lte-example.py

import sys

from subprocess import call

from mininet.cluster.net import MininetCluster
from mininet.cluster.cli import ClusterCLI
from mininet.log import setLogLevel, info
from mininet.util import quietRun

from mininet.lte import *

ENB = 2
UE = 2
TDF = 100
CPU = 1

def emulation ():

    # Use MininetCluster for cluster emulation of hosts and switches
    servers = ['master']
    serverIP = {'master': '127.0.0.1'}
    net = MininetCluster (controller=None, user='root', servers=servers, serverIP=serverIP)
    switches = [None]

    # Add OpenFlow Switches (OVS)
    info ("*** Add OFS\n")
    switch = net.addSwitch ("ofs1", failMode='secure', user='root', server='master', serverIP='127.0.0.1')
    switches.append (switch)

    switch = net.addSwitch ("ofs2", failMode='secure', user='root', server='master', serverIP='127.0.0.1')
    switches.append (switch)

    switch = net.addSwitch ("ofs3", failMode='secure', user='root', server='master', serverIP='127.0.0.1')
    switches.append (switch)

    info ("*** Add link between OFS\n")
    net.addLink (switches[1], switches[2])
    net.addLink (switches[1], switches[3])

    hosts = []
    ueIpList = []
    lteList = []

    # Create one LTE object for each available CPU
    for c in range (0, CPU):
        # Master will responsible for emulation of EPC (MME/SGW/PGW)
        if c == 0:
            MODE = 'Master'
        else:
            MODE = 'Slave'

        LOG = "/tmp/ns-3-log-{0}.txt".format (c)
        UE_IP_BASE = '7.0.{0}.1'.format (c)
        # The TAP interface which is used as junction point of Mininet and NS-3
        SLAVE_DEVICE = 'slaveTap{0}'.format (c)

        # Reference mininet/lte.py for more detail of Lte class
        lte = Lte (nEnbs=ENB / CPU, nUesPerEnb=UE / ENB, tdf=TDF,
                   mode=MODE, epcSwitch=switches[1],
                   server='master', serverIp='127.0.0.1',
                   logFile=LOG, imsiBase=c * (UE / CPU),
                   cellIdBase=c * (ENB / CPU), ueIpBase=UE_IP_BASE, slaveName=SLAVE_DEVICE)

        info ('*** Add eNodeB on LTE {0}\n'.format (c))
        for i in range (c * (ENB / CPU) + 1, (c + 1) * (ENB / CPU) + 1):
            info ('enbTap{0} '.format (i))
            lte.addEnb (switches[2], "enbTap{0}".format (i))
        info ('\n')

        info ('*** Add UE on LTE {0}\n'.format (c))
        for i in range (c * (UE / CPU) + 1, (c + 1) * (UE / CPU) + 1):
            info ('h{0} '.format (i))
            # UE is combination of Mininet host and NS-3 node
            host = net.addHost ("h{0}".format (i), user='root', server='master', serverIP='127.0.0.1', tdf=TDF)
            ueIP = lte.addUe (host)
            # Record IP address for further usage (depends on scenario)
            ueIpList.append (ueIP)
            hosts.append (host)
        info ('\n')

        lteList.append (lte)

    info ('*** net.start ()\n')
    net.start ()

    # Setup DSCP matching flows in OFS1 and OFS2
    switches[1].cmd ("ovs-ofctl add-flow ofs1 priority=0,actions=NORMAL")
    switches[1].cmd ("ovs-ofctl add-flow ofs1 priority=1,ip_dscp=0x00,udp,udp_src=2152,udp_dst=2152,actions=NORMAL")
    switches[1].cmd ("ovs-ofctl add-flow ofs1 priority=2,ip_dscp=0x1a,udp,udp_src=2152,udp_dst=2152,actions=NORMAL")
    switches[1].cmd ("ovs-ofctl add-flow ofs1 priority=3,ip_dscp=0x2e,udp,udp_src=2152,udp_dst=2152,actions=NORMAL")

    switches[2].cmd ("ovs-ofctl add-flow ofs2 priority=0,actions=NORMAL")
    switches[2].cmd ("ovs-ofctl add-flow ofs2 priority=1,ip_dscp=0x00,udp,udp_src=2152,udp_dst=2152,actions=NORMAL")
    switches[2].cmd ("ovs-ofctl add-flow ofs2 priority=2,ip_dscp=0x1a,udp,udp_src=2152,udp_dst=2152,actions=NORMAL")
    switches[2].cmd ("ovs-ofctl add-flow ofs2 priority=3,ip_dscp=0x2e,udp,udp_src=2152,udp_dst=2152,actions=NORMAL")

    info ('*** lte.start ()\n')
    for lte in lteList:
        lte.start ()

    info ('*** Please wait for activation of EPS bearer...\n')
    call ( 'sleep 15', shell=True )
    ClusterCLI (net)

    for lte in lteList:
        lte.stop ()
        lte.clear ()
    net.stop ()

if __name__ == '__main__':
    # example: python lte-example.py 4 4 100 1

    ENB = int (sys.argv[1])
    UE = int (sys.argv[2])
    TDF = int (sys.argv[3])
    CPU = int (sys.argv[4])

    setLogLevel ('info')
    emulation ()
