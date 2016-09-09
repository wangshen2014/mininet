import re
from threading import Thread
from time import sleep
import socket

import mininet.node
import mininet.link
from mininet.log import error, info
from mininet.util import quietRun, errRun, moveIntf
from mininet.cluster.link import RemoteLink

from ns.lte import *
from ns.core import *
from ns.network import *
from ns.internet import *
from ns.mobility import *
from ns.fd_net_device import *
from ns.tap_bridge import *

class Lte (object):
    def __init__ (self, nEnbs=2, nUesPerEnb=1, distance=1000.0, tdf=1,
                  mode='Master', imsiBase=0, cellIdBase=0,
                  ueIpBase='7.0.0.1', ueGwIpAddr='7.0.0.1',
                  pgwIpBase='1.0.0.0', pgwMask='255.0.0.0',
                  homeEnbTxPower=30.0, epcSwitch=None, slaveName='slaveTap'):

        if epcSwitch == None:
            error ('*** error: epcSwitch is a required argument.\n')
            return
        self.epcSwitch = epcSwitch

        if mode == 'Master':
            self.addEpcEntity (self.epcSwitch, 'sgwTap')
            self.addEpcEntity (self.epcSwitch, 'pgwTap')
            self.addEpcEntity (self.epcSwitch, 'mmeTap')
            self.addEpcEntity (self.epcSwitch, 'masterTap')
            self.attachDelay = 10.0
            self.nextAddr = 2
        elif mode == 'Slave':
            Config.SetDefault ("ns3::TapEpcHelper::EpcSlaveDeviceName", StringValue (slaveName))
            self.addEpcEntity (self.epcSwitch, slaveName)
            self.attachDelay = 10.0
            self.nextAddr = 1
        else:
            error ('*** error: mode should be Master or Slave.\n')
            return

        GlobalValue.Bind ("SimulatorImplementationType", StringValue ("ns3::RealtimeSimulatorImpl"))
        GlobalValue.Bind ("ChecksumEnabled", BooleanValue (True))

        Config.SetDefault ("ns3::LteSpectrumPhy::CtrlErrorModelEnabled", BooleanValue (False))
        Config.SetDefault ("ns3::LteSpectrumPhy::DataErrorModelEnabled", BooleanValue (False))

        Config.SetDefault ("ns3::TcpSocket::SegmentSize", UintegerValue (1072))

        Config.SetDefault ("ns3::TapEpcHelper::Mode", StringValue (mode))
        Config.SetDefault ("ns3::LteEnbPhy::TxPower", DoubleValue (homeEnbTxPower))
        LteTimeDilationFactor.SetTimeDilationFactor (tdf)

        self.ueIpBase = ueIpBase
        self.ueGwIpAddr = ueGwIpAddr

        self.lteHelper = LteHelper ()
        self.lteHelper.SetImsiCounter (imsiBase)
        self.lteHelper.SetCellIdCounter (cellIdBase)

        self.tapEpcHelper = TapEpcHelper ()
        self.lteHelper.SetEpcHelper (self.tapEpcHelper)
        self.tapEpcHelper.Initialize ()

        if mode == 'Master':
            pgw = self.tapEpcHelper.GetPgwNode ()

            tap = TapFdNetDeviceHelper ()
            tap.SetDeviceName ("pgwTap")
            tap.SetTapMacAddress (Mac48Address.Allocate ())
            pgwDevice = tap.Install (pgw)

            ipv4Helper = Ipv4AddressHelper ()
            ipv4Helper.SetBase (Ipv4Address (pgwIpBase), Ipv4Mask (pgwMask))
            pgwIpIfaces = ipv4Helper.Assign (pgwDevice)

        positionAlloc = ListPositionAllocator ()
        for i in range (0, nEnbs):
            positionAlloc.Add (Vector (distance * i, 0, 0))

        self.mobility = MobilityHelper ()
        self.mobility.SetMobilityModel ("ns3::ConstantPositionMobilityModel")
        self.mobility.SetPositionAllocator (positionAlloc)

        self.enbLteDevs = NetDeviceContainer ()
        self.ueLteDevs = NetDeviceContainer ()

        self.internetStack = InternetStackHelper ()
        self.internetStack.SetIpv6StackInstall (False)

        self.nsThread = Thread (target = self.run)
        self.tapBridges = []

    def addEpcEntity (self, node, intfName):
        port = node.newPort ()
        self.TapIntf (intfName, node, port)

    def addEnb (self, node, intfName):
        port = node.newPort ()
        self.TapIntf (intfName, node, port)

        nsNode = Node ()
        self.mobility.Install (nsNode)
        enbLteDev = self.lteHelper.InstallEnbDevice (NodeContainer (nsNode))
        self.enbLteDevs.Add (enbLteDev)

    def addUe (self, node):
        node.cmd ('sysctl -w net.ipv6.conf.all.disable_ipv6=1')
        port = node.newPort ()
        intfName = "{0}-eth{1}".format (node.name, port)

        nsNode = Node ()
        self.mobility.Install (nsNode)
        ueLteDev = self.lteHelper.InstallUeDevice (NodeContainer (nsNode))
        self.ueLteDevs.Add (ueLteDev)

        self.internetStack.Install (nsNode)
        self.tapEpcHelper.AssignUeIpv4Address (ueLteDev)

        gatewayMacAddr = self.tapEpcHelper.GetUeDefaultGatewayMacAddress ()
        ip = self.allocateIp ()
        tbIntf = self.TapBridgeIntf (intfName, node, port, nsNode, ueLteDev.Get (0),
                                gatewayMacAddr, self.ueGwIpAddr, ip, self.epcSwitch)
        self.tapBridges.append (tbIntf)

    def allocateIp (self):
        pat = '[0-9]*\.[0-9]*\.[0-9]*\.'
        base = (re.findall (pat, self.ueIpBase))[0]
        ip = "{0}{1}".format (base, str (self.nextAddr))
        self.nextAddr += 1
        return ip

    def start (self):
        if self.nsThread.isAlive ():
            error ('NS-3 thread is already running.\n')
            return

        self.disableIpv6 (self.epcSwitch)

        self.nsThread.start ()

        for i in range (0, len (self.tapBridges)):
            self.tapBridges[i].moveIntoNamespace ()

        self.enableIpv6 (self.epcSwitch)

    def run (self):
        Simulator.Schedule (Seconds (self.attachDelay), LteHelper.Attach,
                            self.lteHelper, self.ueLteDevs)
        Simulator.Stop (Seconds (86400))
        Simulator.Run ()

    def stop (self):
        Simulator.Stop (Seconds (1))
        while self.nsThread.isAlive ():
            sleep (0.1)

    def clear (self):
        Simulator.Destroy ()

    def disableIpv6 (self, localNode):
        localNode.cmd ('sysctl -w net.ipv6.conf.all.disable_ipv6=1')

    def enableIpv6 (self, localNode):
        localNode.cmd ('sysctl -w net.ipv6.conf.all.disable_ipv6=0')

    class TapBridgeIntf (mininet.link.Intf):
        """
        TapBridgeIntf is a Linux TAP interface, which is bridged with an NS-3 NetDevice.
        """
        def __init__ (self, name=None, node=None, port=None,
                      nsNode=None, nsDevice=None, gatewayMacAddr=None,
                      ueGwIpAddr=None, ueIp=None, localNode=None,
                      **params):
            self.name = name
            self.node = node
            self.localNode = localNode
            self.createTap (self.name)
            self.delayedMove = True
            if node.inNamespace == True:
                self.inRightNamespace = False
            else:
                self.inRightNamespace = True
            mininet.link.Intf.__init__ (self, name, node, port, **params)
            self.ueIp = ueIp
            self.ueGwIpAddr = ueGwIpAddr

            tapBridgeHelper = TapBridgeHelper ()
            tapBridgeHelper.SetAttribute ("Mode", StringValue ("ConfigureLocal"))
            tapBridgeHelper.SetAttribute ("DeviceName", StringValue (self.name))
            macAddress = Mac48Address.Allocate ()
            tapBridgeHelper.SetAttribute ("MacAddress", Mac48AddressValue (macAddress))
            self.bridge = tapBridgeHelper.Install (nsNode, nsDevice)

            dev = nsDevice.GetObject (LteUeNetDevice.GetTypeId ())
            dev.SetMacAddress (macAddress)
            dev.SetGatewayMacAddress (gatewayMacAddr)

        def moveIntoNamespace (self):
            while not self.bridge.IsLinkUp ():
                sleep (0.1)
            moveIntf (self.name, self.node)
            self.node.cmd ('ip link set dev {0} up'.format (self.name))
            self.node.cmd ('ip addr add dev {0} {1}/8'.format (self.name, self.ueIp))
            self.node.cmd ('ip route add default via {0}'.format (self.ueGwIpAddr))
            self.node.cmd ('arp -s {0} 00:00:00:00:00:00'.format (self.ueGwIpAddr))
            pat = '[0-9]*\.'
            route = (re.findall (pat, self.ueIp))[0] + '0.0.0'
            self.node.cmd ('ip route del {0}/8'.format (route))

        def cmd (self, *args, **kwargs):
            if self.inRightNamespace == True:
                return self.node.cmd (*args, **kwargs)
            else:
                return self.localNode.cmd (*args, **kwargs)

        def createTap (self, name):
            self.node.cmd ('ip tuntap add {0} mode tap'.format (name))
            self.node.cmd ('ip link set dev {0} netns 1'.format (name))

    class TapIntf (mininet.link.Intf):
        """
        TapIntf is a Linux TAP interface.
        """
        def __init__ (self, name=None, node=None, port=None, **params):
            self.name = name
            self.node = node
            self.createTap (self.name)
            mininet.link.Intf.__init__ (self, self.name, node, port, **params)

        def createTap (self, name):
            self.node.cmd ('ip tuntap add {0} mode tap'.format (name))

class LteCluster (object):
    def __init__ (self, nEnbs=2, nUesPerEnb=1, distance=1000.0, tdf=1,
                  mode='Master', imsiBase=0, cellIdBase=0,
                  ueIpBase='7.0.0.1', ueGwIpAddr='7.0.0.1',
                  pgwIpBase='1.0.0.0', pgwMask='255.0.0.0',
                  epcSwitch=None, server=None, serverIp=None, port=53724, logFile=None,
                  homeEnbTxPower=30.0, slaveName='slaveTap'):

        if epcSwitch == None:
            error ('*** error: epcSwitch is a required argument.\n')
            return
        elif server == None:
            error ('*** error: server is a required argument.\n')
            return
        elif serverIp == None:
            error ('*** error: serverIp is a required argument.\n')
            return

        self.epcSwitch = epcSwitch
        self.server = server
        self.serverIp = serverIp
        self.ueIpBase = ueIpBase
        self.ueGwIpAddr = ueGwIpAddr
        self.tapBridgeIntfs = []

        self.startDeamon ()
        self.csock = self.connectDaemon (serverIp, port)

        if mode == 'Master':
            self.addEpcEntity (self.epcSwitch, 'pgwTap')
            self.addEpcEntity (self.epcSwitch, 'sgwTap')
            self.addEpcEntity (self.epcSwitch, 'mmeTap')
            self.addEpcEntity (self.epcSwitch, 'masterTap')
            self.nextAddr = 2

        elif mode == 'Slave':
            cmd = 'Config.SetDefault ("ns3::TapEpcHelper::EpcSlaveDeviceName", StringValue ("{0}"))\n'.format (str (slaveName))
            self.csock.sendall (cmd)
            IpBase = re.sub (r'[0-9]*\.([0-9]*\.[0-9]*\.[0-9])', r'0.\1', ueIpBase)
            cmd = 'Config.SetDefault ("ns3::TapEpcHelper::SlaveUeIpAddressBase", StringValue ("{0}"))\n'.format (str (IpBase))
            self.csock.sendall (cmd)
            cmd = 'Config.SetDefault ("ns3::TapEpcHelper::SlaveIpAddressBase", StringValue ("{0}"))\n'.format (str (IpBase))
            self.csock.sendall (cmd)
            self.addEpcEntity (self.epcSwitch, slaveName)
            self.nextAddr = 1

        else:
            error ('*** error: mode should be Master or Slave.\n')
            self.csock.sendall ("exit")
            return

        cmd = 'nEnbs = {0}\n'.format (str (nEnbs))
        self.csock.sendall (cmd)
        cmd = 'nUesPerEnb = {0}\n'.format (str (nUesPerEnb))
        self.csock.sendall (cmd)
        #cmd = 'attachDelay = 10.0\n'
        cmd = 'attachDelay = 10.0\n'
        self.csock.sendall (cmd)
        cmd = 'distance = {0}\n'.format (str (distance))
        self.csock.sendall (cmd)

        #cmd = 'LogComponentEnable ("TapEpcHelper", LOG_LEVEL_ALL)\n'
        #self.csock.sendall (cmd)
        #cmd = 'LogComponentEnable ("EpcSgwPgwApplication", LOG_LEVEL_ALL)\n'
        #self.csock.sendall (cmd)
        cmd = 'LogComponentEnable ("LteEnbRrc", LOG_LEVEL_ALL)\n'
        self.csock.sendall (cmd)
        #cmd = 'LogComponentEnable ("RealtimeSimulatorImpl", LOG_LEVEL_ALL)\n'
        #self.csock.sendall (cmd)

        cmd = 'GlobalValue.Bind ("SimulatorImplementationType", StringValue ("ns3::RealtimeSimulatorImpl"))\n'
        self.csock.sendall (cmd)
        cmd = 'GlobalValue.Bind ("ChecksumEnabled", BooleanValue (True))\n'
        self.csock.sendall (cmd)

        cmd = 'Config.SetDefault ("ns3::LteSpectrumPhy::CtrlErrorModelEnabled", BooleanValue (False))\n'
        self.csock.sendall (cmd)
        cmd = 'Config.SetDefault ("ns3::LteSpectrumPhy::DataErrorModelEnabled", BooleanValue (False))\n'
        self.csock.sendall (cmd)

        cmd = 'Config.SetDefault ("ns3::TcpSocket::SegmentSize", UintegerValue (1072))\n'
        self.csock.sendall (cmd)

        cmd = 'Config.SetDefault ("ns3::LteHelper::Scheduler", StringValue ("ns3::FdMtFfMacScheduler"))\n'
        self.csock.sendall (cmd)
        cmd = 'Config.SetDefault ("ns3::TapEpcHelper::Mode", StringValue ("{0}"))\n'.format (mode)
        self.csock.sendall (cmd)
        cmd = 'Config.SetDefault ("ns3::LteEnbPhy::TxPower", DoubleValue ({0}))\n'.format (homeEnbTxPower)
        self.csock.sendall (cmd)
        cmd = 'Config.SetDefault ("ns3::LteEnbRrc::DefaultTransmissionMode", UintegerValue (2))\n'
        self.csock.sendall (cmd)

        cmd = 'Config.SetDefault ("ns3::LteEnbNetDevice::UlBandwidth", UintegerValue ({0}))\n'.format (100)
        self.csock.sendall (cmd)
        cmd = 'Config.SetDefault ("ns3::LteEnbNetDevice::DlBandwidth", UintegerValue ({0}))\n'.format (100)
        self.csock.sendall (cmd)

        cmd = 'LteTimeDilationFactor.SetTimeDilationFactor ({0})\n'.format (tdf)
        self.csock.sendall (cmd)
        
        if logFile != None:
            cmd = 'Config.SetDefault ("ns3::TapEpcHelper::LogFile", StringValue ("{0}"))\n'.format (logFile)
            self.csock.sendall (cmd)

        cmd = 'lteHelper = LteHelper ()\n'
        self.csock.sendall (cmd)
        cmd = 'lteHelper.SetImsiCounter ({0})\n'.format (str (imsiBase))
        self.csock.sendall (cmd)
        cmd = 'lteHelper.SetCellIdCounter ({0})\n'.format (str (cellIdBase))
        self.csock.sendall (cmd)

        cmd = 'tapEpcHelper = TapEpcHelper ()\n'
        self.csock.sendall (cmd)
        cmd = 'lteHelper.SetEpcHelper (tapEpcHelper)\n'
        self.csock.sendall (cmd)
        cmd = 'tapEpcHelper.Initialize ()\n'
        self.csock.sendall (cmd)

        if mode == 'Master':
            cmd = 'pgw = tapEpcHelper.GetPgwNode ()\n'
            self.csock.sendall (cmd)

            cmd = 'tap = TapFdNetDeviceHelper ()\n'
            self.csock.sendall (cmd)
            cmd = 'tap.SetDeviceName ("pgwTap")\n'
            self.csock.sendall (cmd)
            cmd = 'tap.SetTapMacAddress (Mac48Address.Allocate ())\n'
            self.csock.sendall (cmd)
            cmd = 'pgwDevice = tap.Install (pgw)\n'
            self.csock.sendall (cmd)

            cmd = 'ipv4Helper = Ipv4AddressHelper ()\n'
            self.csock.sendall (cmd)
            cmd = 'ipv4Helper.SetBase (Ipv4Address ("{0}"), Ipv4Mask ("{1}"))\n'.format (str (pgwIpBase), str (pgwMask))
            self.csock.sendall (cmd)
            cmd = 'pgwIpIfaces = ipv4Helper.Assign (pgwDevice)\n'
            self.csock.sendall (cmd)

            # cmd = 'ipv4 = pgw.GetObject (Ipv4.GetTypeId ())\n'
            # self.csock.sendall (cmd)
            # cmd = 'ipv4Static = Ipv4StaticRoutingHelper ().GetStaticRouting (ipv4)\n'
            # self.csock.sendall (cmd)
            # cmd = 'ipv4Static.SetDefaultRoute (Ipv4Address ("{0}"), 3)\n'.format ("1.0.0.1")
            # self.csock.sendall (cmd)

        cmd = 'positionAlloc = ListPositionAllocator ()\n'
        self.csock.sendall (cmd)
        cmd = 'for i in range (0, nEnbs):\n    positionAlloc.Add (Vector (distance * i, 0, 0))\n'
        self.csock.sendall (cmd)

        cmd = 'mobility = MobilityHelper ()\n'
        self.csock.sendall (cmd)
        cmd = 'mobility.SetMobilityModel ("ns3::ConstantPositionMobilityModel")\n'
        self.csock.sendall (cmd)
        cmd = 'mobility.SetPositionAllocator (positionAlloc)\n'
        self.csock.sendall (cmd)

        cmd = 'enbLteDevs = NetDeviceContainer ()\n'
        self.csock.sendall (cmd)
        cmd = 'ueLteDevs = NetDeviceContainer ()\n'
        self.csock.sendall (cmd)

        cmd = 'internetStack = InternetStackHelper ()\n'
        self.csock.sendall (cmd)
        cmd = 'internetStack.SetIpv6StackInstall (False)\n'
        self.csock.sendall (cmd)

        cmd = 'def run (attachDelay, lteHelper, ueLteDevs):\n'
        cmd += '    Simulator.Schedule (Seconds (attachDelay), LteHelper.Attach, lteHelper, ueLteDevs)\n'
        cmd += '    Simulator.Stop (Seconds (86400))\n'
        cmd += '    Simulator.Run ()\n'
        self.csock.sendall (cmd)

        cmd = 'nsThread = Thread (target = run, args = (attachDelay, lteHelper, ueLteDevs))\n'
        self.csock.sendall (cmd)
        cmd = 'tapBridges = []\n'
        self.csock.sendall (cmd)

    def startDeamon (self):
        self.epcSwitch.cmd ("python /usr/bin/opennet-daemon.py start")

    def stopDeamon (self):
        self.epcSwitch.cmd ("python /usr/bin/opennet-daemon.py stop")

    def connectDaemon (self, ip, port):
        csock = socket.socket (socket.AF_INET, socket.SOCK_STREAM)
        csock.connect ((ip, port))
        return csock

    def addEpcEntity (self, node, intfName):
        port = node.newPort ()
        self.TapIntf (intfName, node, port)

    def addEnb (self, node, intfName):
        port = node.newPort ()
        self.TapIntf (intfName, node, port)

        cmd = 'nsNode = Node ()\n'
        self.csock.sendall (cmd)
        cmd = 'mobility.Install (nsNode)\n'
        self.csock.sendall (cmd)
        cmd = 'enbLteDev = lteHelper.InstallEnbDevice (NodeContainer (nsNode))\n'
        self.csock.sendall (cmd)
        cmd = 'enbLteDevs.Add (enbLteDev)\n'
        self.csock.sendall (cmd)

    def addUe (self, node):
        node.cmd ('sysctl -w net.ipv6.conf.all.disable_ipv6=1')
        port = node.newPort ()
        intfName = "{0}-eth{1}".format (node.name, port)

        cmd = 'nsNode = Node ()\n'
        self.csock.sendall (cmd)
        cmd = 'mobility.Install (nsNode)\n'
        self.csock.sendall (cmd)
        cmd = 'ueLteDev = lteHelper.InstallUeDevice (NodeContainer (nsNode))\n'
        self.csock.sendall (cmd)
        cmd = 'ueLteDevs.Add (ueLteDev)\n'
        self.csock.sendall (cmd)

        cmd = 'internetStack.Install (nsNode)\n'
        self.csock.sendall (cmd)
        cmd = 'tapEpcHelper.AssignUeIpv4Address (ueLteDev)\n'
        self.csock.sendall (cmd)

        cmd = 'gatewayMacAddr = tapEpcHelper.GetUeDefaultGatewayMacAddress ()\n'
        self.csock.sendall (cmd)

        ueIp = self.allocateIp ()
        tbIntf = self.TapBridgeIntf (intfName, node, port, self.ueGwIpAddr, ueIp, self.epcSwitch, self.csock)
        self.tapBridgeIntfs.append (tbIntf)
        return ueIp

    def allocateIp (self):
        pat = '[0-9]*\.[0-9]*\.[0-9]*\.'
        base = (re.findall (pat, self.ueIpBase))[0]
        ip = "{0}{1}".format (base, str (self.nextAddr))
        self.nextAddr += 1
        return ip

    def start (self):
        cmd = 'if nsThread.isAlive ():\n    csock.sendall ("True")\nelse:\n    csock.sendall ("False")\n'
        self.csock.sendall (cmd)
        data = self.csock.recv (4096)
        if data == "True":
            error ('*** NS-3 thread is already running\n')
            return
        elif data == "False":
            info ('*** Starting NS-3 thread\n')

        self.disableIpv6 (self.epcSwitch)

        cmd = 'nsThread.start ()\n'
        self.csock.sendall (cmd)

        info ('*** moveIntoNamespace\n')
        for tbIntf in self.tapBridgeIntfs:
            info ('{0} '.format (tbIntf.name))
            tbIntf.moveIntoNamespace ()
        info ('\n')
        
        self.enableIpv6 (self.epcSwitch)

    def stop (self):
        cmd = 'Simulator.Stop (Seconds (1))\n'
        self.csock.sendall (cmd)
        cmd = 'while nsThread.isAlive ():\n    sleep (0.1)\n'
        self.csock.sendall (cmd)

    def clear (self):
        cmd = 'Simulator.Destroy ()\n'
        self.csock.sendall (cmd)
        cmd = 'exit ()\n'
        self.csock.sendall (cmd)
        self.csock.close ()
        self.stopDeamon ()

    def disableIpv6 (self, localNode):
        localNode.cmd ('sysctl -w net.ipv6.conf.all.disable_ipv6=1')

    def enableIpv6 (self, localNode):
        localNode.cmd ('sysctl -w net.ipv6.conf.all.disable_ipv6=0')

    class TapIntf (mininet.link.Intf):
        """
        TapIntf is a Linux TAP interface.
        """
        def __init__ (self, name=None, node=None, port=None, **params):
            self.name = name
            self.node = node
            self.createTap (self.name)
            mininet.link.Intf.__init__ (self, self.name, node, port, **params)

        def createTap (self, name):
            self.node.cmd ('ip tuntap add {0} mode tap'.format (name))

    class TapBridgeIntf (mininet.link.Intf):
        """
        TapBridgeIntf is a Linux TAP interface, which is bridged with an NS-3 NetDevice.
        """
        def __init__ (self, name=None, node=None, port=None, ueGwIpAddr=None, ueIp=None,
                      localNode=None, csock=None, **params):
            self.name = name
            self.node = node
            self.ueGwIpAddr = ueGwIpAddr
            self.ueIp = ueIp
            self.localNode = localNode
            self.csock = csock
            self.createTap (self.name)
            self.delayedMove = True
            if node.inNamespace == True:
                self.inRightNamespace = False
            else:
                self.inRightNamespace = True
            mininet.link.Intf.__init__ (self, name, node, port, **params)

            cmd = 'nsDevice = ueLteDev.Get (0)\n'
            self.csock.sendall (cmd)

            cmd = 'tapBridgeHelper = TapBridgeHelper ()\n'
            self.csock.sendall (cmd)
            cmd = 'tapBridgeHelper.SetAttribute ("Mode", StringValue ("ConfigureLocal"))\n'
            self.csock.sendall (cmd)
            cmd = 'tapBridgeHelper.SetAttribute ("DeviceName", StringValue ("{0}"))\n'.format (str (self.name))
            self.csock.sendall (cmd)
            cmd = 'macAddress = Mac48Address.Allocate ()\n'
            self.csock.sendall (cmd)
            cmd = 'tapBridgeHelper.SetAttribute ("MacAddress", Mac48AddressValue (macAddress))\n'
            self.csock.sendall (cmd)
            cmd = 'tb = tapBridgeHelper.Install (nsNode, nsDevice)\n'
            self.csock.sendall (cmd)
            cmd = 'tapBridges.append (tb)\n'
            self.csock.sendall (cmd)

            cmd = 'dev = nsDevice.GetObject (LteUeNetDevice.GetTypeId ())\n'
            self.csock.sendall (cmd)
            cmd = 'dev.SetMacAddress (macAddress)\n'
            self.csock.sendall (cmd)
            cmd = 'dev.SetGatewayMacAddress (gatewayMacAddr)\n'
            self.csock.sendall (cmd)

        def moveIntoNamespace (self):
            while True:
                cmd = 'if tapBridges[-1].IsLinkUp():\n    csock.sendall ("True")\nelse:\n    csock.sendall ("False")\n'
                self.csock.sendall (cmd)
                data = self.csock.recv (4096)
                if data == "True":
                    break
                else:
                    sleep (0.1)

            RemoteLink.moveIntf (self.name, self.node)

            self.node.cmd ('ip link set dev {0} up'.format (self.name))
            self.node.cmd ('ip addr add dev {0} {1}/8'.format (self.name, self.ueIp))
            self.node.cmd ('ip route add default via {0}'.format (self.ueGwIpAddr))
            self.node.cmd ('arp -s {0} 00:00:00:00:00:00'.format (self.ueGwIpAddr))
            pat = '[0-9]*\.'
            route = (re.findall (pat, self.ueIp))[0] + '0.0.0'
            self.node.cmd ('ip route del {0}/8'.format (route))

        def cmd (self, *args, **kwargs):
            if self.inRightNamespace == True:
                return self.node.cmd (*args, **kwargs)
            else:
                return self.localNode.cmd (*args, **kwargs)

        def createTap (self, name):
            self.node.cmd ('ip tuntap add {0} mode tap'.format (name))
            self.node.cmd ('ip link set dev {0} netns 1'.format (name))
