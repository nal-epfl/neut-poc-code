import os
import numpy as np

from helper_methods import *


def reset_tc(interface):
    print('Remove current tc stuff')
    os.system('sudo tc qdisc del dev {} root'.format(interface))
    os.system('sudo tc qdisc del dev {} handle ffff: ingress'.format(interface))
    os.system('sudo modprobe -r ifb')
    

# The policer is implemented with Token Bucket Filter (TBF) and it have three parameters:
# rate: the rate at which tokens are generated
# burst: the size of the bucket keeping the tokens (can be set directly or dynamically acc. to rate and burst_period)
# limit: the size of the queue while processing packets by TBF (can be set directly or as ratio of the burst)
class PolicerConfig:
    def __init__(self, rate, use_burst_period, burst_param, use_limit_ratio=False, limit_param=15000):
        self.rate = rate
        self.burst = self.get_burst(rate, burst_param) if use_burst_period else burst_param
        self.limit = self.get_limit(self.burst, limit_param) if use_limit_ratio else limit_param # minimum should be 10MTU
        
    @staticmethod
    def get_rate(rate_ratio, traffic_volume):
        return int(np.round(traffic_volume / rate_ratio))

    @staticmethod
    def get_burst(rate, burst_period):
        return int(rate * burst_period * 125000)

    @staticmethod
    def get_limit(burst, limit_ratio):
        return max(int(burst * float(limit_ratio)), 15000)
    
    def to_json(self):
        return {'rate': self.rate, 'burst': self.burst, 'limit': self.limit}


class TCPolicer:
    def __init__(self, target_srcs, eth_interface, ifb, config, traffic_tag=100):
        self.target_srcs = target_srcs
        self.interface = eth_interface
        self.ifb = ifb
        self.ifb_dump = None
        self.config = config
        self.traffic_tag = traffic_tag

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
                'sudo tc filter add dev {} parent ffff: protocol all pref 99 u32 '
                'match ip{} src {} '
                'action mirred egress redirect index {} dev {} '
                'action drop'.format(self.interface, '6' if is_ipv6(src) else '', src, self.traffic_tag, self.ifb)
            )

        if added_latency:
            os.system('sudo tc qdisc add dev {} root handle 1: netem delay {} limit {}'.format(
                self.ifb, added_latency, max(self.config.limit, 30 * 1500)))
            os.system('sudo tc qdisc add dev {} parent 1:1 handle 10: tbf rate {} burst {} limit {}'.format(
                self.ifb, self.config.rate, self.config.burst, 7500))
        else:
            os.system('sudo tc qdisc add dev {} root handle 1: tbf rate {} burst {} limit {}'.format(
                self.ifb, self.config.rate, self.config.burst, self.config.limit))

        print('Policing is now enabled for {}. Do not forget to --reset_tc when you are done.'.format(self.target_srcs))


    def start_tcpdump(self, temp_dir, ports):
        ifb_temp_pcap = '{}/tcpdump_out_{}.pcap'.format(temp_dir, self.ifb)
        self.ifb_dump = Tcpdump(dump_path=ifb_temp_pcap, interface=self.ifb)
        self.ifb_dump.start(ports)

    def stop_tcpdump(self, out_dir, user_tag):
        if self.ifb_dump:
            out_pcap = '{}/dump_{}_{}.pcap'.format(out_dir, user_tag, self.ifb)
            self.ifb_dump.stop()
            self.ifb_dump.clean_pcap(out_pcap, get_ip(self.interface))






