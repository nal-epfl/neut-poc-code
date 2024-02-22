import os
import numpy as np

from helper_methods import *


def reset_tc(interface):
    print('Remove current tc stuff')
    os.system('sudo tc qdisc del dev {} root'.format(interface))
    os.system('sudo tc qdisc del dev {} handle ffff: ingress'.format(interface))
    os.system('sudo modprobe -r ifb')


class TCPolicer:
    def __init__(self, target_srcs, eth_interface, ifb, rate, burst, limit=15000, traffic_tag=100):
        self.target_srcs = target_srcs
        self.interface = eth_interface
        self.ifb = ifb
        self.ifb_dump = None
        self.rate = rate
        self.burst = burst
        self.limit = limit
        self.traffic_tag = traffic_tag

    @staticmethod
    def get_rate(rate_ratio, traffic_volume):
        return int(np.round(traffic_volume / rate_ratio))

    @staticmethod
    def get_burst(rate, burst_period):
        return int(rate * burst_period * 125000)

    @staticmethod
    def get_limit(burst, limit_ratio):
        return max(int(burst * float(limit_ratio)), 15000)

    def reset_interfaces(self):
        reset_tc(self.interface)

    def enable_policing(self, added_latency=None):
        # create the ifb interface
        os.system('sudo modprobe ifb')
        os.system('sudo ifconfig {} up'.format(self.ifb))
        os.system('sudo ifconfig {} txqueuelen 1'.format(self.ifb))

        # forward inbound traffic to ifb
        os.system('sudo tc qdisc add dev {} root fq maxrate 10gbit'.format(self.interface))
        os.system('sudo tc qdisc add dev {} handle ffff: ingress'.format(self.interface))
        for i, src in enumerate(self.target_srcs):
            os.system(
                'sudo tc filter add dev {} parent ffff: protocol all pref {} u32 '
                'match ip{} src {} '
                'action mirred egress redirect index {} dev {} '
                'action drop'.format(self.interface, self.traffic_tag, '6' if is_ipv6(src) else '', src, self.traffic_tag, self.ifb)
            )

        if added_latency:
            os.system('sudo tc qdisc add dev {} root handle 1: netem delay {} limit {}'.format(
                self.ifb, added_latency, max(self.limit, 30 * 1500)))
            os.system('sudo tc qdisc add dev {} parent 1:1 handle 10: tbf rate {} burst {} limit {}'.format(
                self.ifb, self.rate, self.burst, 7500))
        else:
            os.system('sudo tc qdisc add dev {} root handle 1: tbf rate {} burst {} limit {}'.format(
                self.ifb, self.rate, self.burst, self.limit))

        print('Policing is now enabled for {}. Do not forget to --reset_tc when you are done.'.format(self.target_srcs))

    def get_tbf_params(self):
        return self.rate, self.burst, self.limit

    def start_tcpdump(self, temp_dir, ports):
        ifb_temp_pcap = '{}/tcpdump_out_{}.pcap'.format(temp_dir, self.ifb)
        self.ifb_dump = Tcpdump(dump_path=ifb_temp_pcap, interface=self.ifb)
        self.ifb_dump.start(ports)

    def stop_tcpdump(self, out_dir, user_tag):
        if self.ifb_dump:
            out_pcap = '{}/dump_{}_{}.pcap'.format(out_dir, user_tag, self.ifb)
            self.ifb_dump.stop()
            self.ifb_dump.clean_pcap(out_pcap, get_ip(self.interface))






