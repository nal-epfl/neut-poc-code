"""
by: Zeinab Shmeis (zeinab.shmeis@epfl.ch)

Example:
    python runProofOfConcept.py --reset_tc --interface=enp0s31f6 --ifb=ifb0
    python runProofOfConcept.py --enable_policing --interface=enp0s31f6 --target_srcs=128.178.122.153/32 --rate=5mbit --burst=1500 --limit=1500 --ifb=ifb0
    python runProofOfConcept.py --run --app=youtube --interface=eno1 --rate=20mbit --burst=1500 --limit=1500 --background_traces=traces
    python runProofOfConcept.py --run --auto_config --app=youtube --interface=eno1 --rate=20mbit --limit_as_ratio=0.75 --background_traces=traces

Note:
    the rule of thumb to set the burst = rate(mbit) * rtt(sec) * 125000
"""
import multiprocessing

import numpy as np
import argparse, requests, os, socket, time
import re, json, itertools
from multiprocessing import Process

from IOPaths import *
from helper_methods import *
import background_replay.replayBackground as backReplay
import test_downloads.downloadTests as testDownloader

udp_wehe_apps = {"meet", "teams", "skype", "twittervideo", "webex", "whatsapp", "zoom"}
tcp_wehe_apps = {
    "youtube", "netflix", "twitch", "hulu", "spotify", "disneyplus", "facebookvideo", "dailymotion", "deezer",
    "nbcsports", "molotovtv", "mycanal", "ocs", "amazon", "salto", "sfrplay", "vimeo"
}
wehe_apps = {"youtube", "amazon", "nbcsports", "netflix", "facebookvideo"}
wehe_ports = ['443', '3480', '8801', '9000', '19305', '3478', '49882']


def get_nearest_mlab_servers():
    print('Fetch Nearest M-Lab servers')
    data = requests.get('https://locate.measurementlab.net/v2/nearest/wehe/replay').json()
    servers = [record['machine'] for record in data['results']]
    servers_ips = {s: '{}/24'.format(socket.gethostbyname(s)) for s in servers}
    return servers_ips


def get_all_mlab_servers():
    print('Fetch All M-Lab servers')
    mlab_servers_df = extract_table_from_html('https://locate.measurementlab.net/admin/sites')
    servers_ips = {}
    for server_id in mlab_servers_df['Site ID']:
        for mlabi in ['mlab1', 'mlab2', 'mlab3', 'mlab4']:
            try:
                server_name = '{}-{}.mlab-oti.measurement-lab.org'.format(mlabi, server_id)

                ipv4 = socket.getaddrinfo(server_name, None, socket.AF_INET)[0][4][0]
                servers_ips['{}_ipv4'.format(server_name)] = '{}/24'.format(ipv4)

                ipv6 = socket.getaddrinfo(server_name, None, socket.AF_INET6)[0][4][0]
                servers_ips['{}_ipv6'.format(server_name)] = '{}/64'.format(ipv6)
            except Exception as e:
                continue
    with open("mlab_servers.json", "w") as write_file:
        json.dump(servers_ips, write_file, indent=4)
    return servers_ips


def get_epfl_servers():
    with open(os.path.join(WEHE_CMDLINE_DIR, 'res/servers_ip_list.txt'), 'r') as f:
        return ['{}/32'.format(ip.rstrip('\n')) for ip in f.readlines()]


def get_background_server():
    with open(os.path.join(BACKGROUND_REPLAY_DIR, 'client_info.json'), 'r') as f:
        return '{}/32'.format(json.load(f)['ip'])


def get_remote_back_credentials():
    with open(os.path.join(BACKGROUND_REPLAY_DIR, 'client_info.json'), 'r') as f:
        return json.load(f)


def reset_tc(interface, ifb='ifb0'):
    print('Remove current tc stuff')
    os.system('sudo tc qdisc del dev {} root'.format(interface))
    os.system('sudo tc qdisc del dev {} handle ffff: ingress'.format(interface))
    os.system('sudo modprobe -r ifb')


def enable_policing(interface, target_srcs, rate, burst, limit=15000, ifb='ifb0'):
    reset_tc(interface=interface, ifb=ifb)

    # create the ifb interface
    os.system('sudo modprobe ifb')
    os.system('sudo ifconfig {} up'.format(ifb))
    os.system('sudo ifconfig {} txqueuelen 1'.format(ifb))

    # forward inbound traffic to ifb
    os.system('sudo tc qdisc add dev {} root fq maxrate 10gbit'.format(interface))
    os.system('sudo tc qdisc add dev {} handle ffff: ingress'.format(interface))
    for i, src in enumerate(target_srcs):
        os.system(
            'sudo tc filter add dev {} parent ffff: protocol all pref 99 u32 '
            'match ip{} src {} '
            'action mirred egress redirect index 100 dev {} '
            'action drop'.format(interface, '6' if is_ipv6(src) else '', src, ifb)
        )

    # os.system('sudo tc qdisc add dev {} root handle 1: tbf rate {} burst {} limit {}'.format(ifb, rate, burst, limit))

    os.system('sudo tc qdisc add dev {} root handle 1: netem delay 34ms limit {}'.format(ifb, max(limit, 30*1500)))
    os.system('sudo tc qdisc add dev {} parent 1:1 handle 10: tbf rate {} burst {} limit {}'.format(ifb, rate, burst, 7500))

    print('Policing is now enabled. Do not forget to --reset_tc when you are done.')


def start_background_server(interface, protocol='tcp'):
    server_ip = get_ip(interface)
    print('Start background server with ip={}'.format(server_ip))
    backReplay.run_server(server_ip=server_ip, protocol=protocol)


def flush_replay_background():
    # kill any background process if exists
    for process in multiprocessing.active_children(): process.kill()

    # kill background server on this machine if it exists
    backReplay.kill_server()

    # kill all clients on the remote machine
    back_client_info = get_remote_back_credentials()
    command = 'kill -9 $(ps ax | grep \'replayBackground.py\' | awk \'{print $1}\')'
    execute_remote_command(back_client_info['ip'], back_client_info['user'], back_client_info['pass'], command)


def run_wehe_test(wehe_app):
    os.chdir(WEHE_CMDLINE_DIR)
    os.system('java -jar wehe-cmdline.jar -s epfl -n {} -c -r results/ -l info -u 2'.format(wehe_app))
    os.chdir('..')
    return testDownloader.get_run_test_info('{}/results'.format(WEHE_CMDLINE_DIR))


def run_proof_of_concept(wehe_app, interface, with_policing, rate, burst, limit, background_dir='traces'):
    # enable policing
    senders = np.concatenate([[get_background_server()], get_epfl_servers()]) # list(get_all_mlab_servers().values())])
    if with_policing:
        enable_policing(interface=interface, target_srcs=senders, rate=rate, burst=burst, limit=limit)

    # find application protocol
    app_protocol = 'tcp' if wehe_app in tcp_wehe_apps else 'udp'

    # load the background server info
    back_client_info = get_remote_back_credentials()

    # reset background server and client
    flush_replay_background()

    # start background server
    back_process = Process(target=start_background_server, kwargs={'interface': interface, 'protocol': app_protocol})
    back_process.start()
    print('Background server is running.')
    print('Do not forget to start the background client replays. Wehe CLI test will start in 1 min.')

    # start background client on the remote machine
    command = ('ulimit -n 1048576 && cd {} && python3 replayBackground.py --multi_clients --traces_dir=./{} --server_ip={} --protocol={}'.format(
        back_client_info['path'], background_dir, get_ip(interface), app_protocol
    ))
    execute_remote_command(back_client_info['ip'], back_client_info['user'], back_client_info['pass'], command)

    # sleep for warmup
    time.sleep(10)

    try:
        # start tcpdump from client side
        if (app_protocol == 'udp') and enable_policing:
            ifb_temp_pcap = '{}/results/tcpdump_ifb_out.pcap'.format(WEHE_CMDLINE_DIR)
            ifb_dump = Tcpdump(dump_path=ifb_temp_pcap, interface='ifb0')
            ifb_dump.start(wehe_ports + ['1234'])

            eth_temp_pcap = '{}/results/tcpdump_eth_out.pcap'.format(WEHE_CMDLINE_DIR)
            eth_dump = Tcpdump(dump_path=eth_temp_pcap, interface='ifb0')
            eth_dump.start(wehe_ports + ['1234'])

        # start the wehe cli test
        test_info = run_wehe_test(wehe_app=wehe_app)

        # clean everything
        flush_replay_background()
        reset_tc(interface=interface)

        # save the test information
        test_info['background'] = background_dir
        test_info['rate'], test_info['burst'], test_info['limit'], test_info['app'] = rate, burst, limit, wehe_app
        output_dir = '{}/{}'.format(TESTS_INFO_DIR, test_info['date'].replace('/', '-'))
        os.makedirs(output_dir, exist_ok=True)
        with open('{}/test_{}_{}_info.json'.format(output_dir, test_info['user_id'], test_info['test_id']), 'w') as f:
            json.dump(test_info, f)

        # stop and copy tcpdump output
        if (app_protocol == 'udp') and enable_policing:
            ifb_out_pcap = '{}/dump_{}_{}.pcap'.format(output_dir, test_info['user_id'], test_info['test_id'])
            ifb_dump.stop()
            ifb_dump.clean_pcap(ifb_out_pcap, get_ip(interface))
            print('done cleaning pcap for ifb interface')

            eth_out_pcap = '{}/dump_{}_{}_eth.pcap'.format(output_dir, test_info['user_id'], test_info['test_id'])
            eth_dump.stop()
            eth_dump.clean_pcap(eth_out_pcap, get_ip(interface))
            print('done cleaning pcap for eth interface')
    except Exception as e:
        flush_replay_background()
        reset_tc(interface=interface)
        print('failed to record policer configuration because of: ', e)


if __name__ == '__main__':

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--reset_tc', action='store_true')
    arg_parser.add_argument('--enable_policing', action='store_true')
    arg_parser.add_argument('--run', action='store_true')
    arg_parser.add_argument('--auto_config', action='store_true')
    arg_parser.add_argument('--interface')
    arg_parser.add_argument('--ifb', default='ifb0')
    arg_parser.add_argument('--target_srcs', action='append', type=str)
    arg_parser.add_argument('--rate')
    arg_parser.add_argument('--burst')
    arg_parser.add_argument('--limit')
    arg_parser.add_argument('--limit_as_ratio')
    arg_parser.add_argument('--app')
    arg_parser.add_argument('--background_traces', default='traces')
    arg_parser.add_argument('--run_exp', action='store_true')
    args = arg_parser.parse_args()

    if args.reset_tc:
        reset_tc(args.interface, args.ifb)
    elif args.enable_policing:
        enable_policing(args.interface, args.target_srcs, args.rate, args.burst, args.limit, args.ifb)
    elif args.run & args.auto_config:
        rate = float(re.findall("\d+\.?\d+", args.rate)[0])
        burst = int(rate * (20 * 1e-3) * 125000)
        limit = int(burst * float(args.limit_as_ratio))
        run_proof_of_concept(args.app, args.interface, True, args.rate, burst, limit, args.background_traces)
    elif args.run:
        run_proof_of_concept(args.app, args.interface, True, args.rate, args.burst, args.limit, args.background_traces)
    elif args.run_exp:
        # apps and total traffic volume mapping
        app_volumes = {
            # 'skype': 28.8, 'probe1skype': 27.4, 'probe2skype': 29,
            # 'whatsapp': 43.4, 'probewhatsapp': 27,
            'webex': 27, 'incprobewebex': 27, 'probe2webex': 27,
            # 'nbcsports': 65, 'netflix': 57, 'facebookvideo': 65
            # 'nbcsports': 34, 'netflix': 32, 'facebookvideo': 37
        }
        burst_period = 0.035
        rate_ratios, limit_ratios = [1.3, 1.5, 2, 2.5], [0.25, 0.5, 1]
        nb_runs = 0
        for back_dir_idx in np.arange(1, 6):
            for rate_ratio, limit_ratio in itertools.product(rate_ratios, limit_ratios):
                for app in app_volumes.keys():
                    rate = int(np.round(app_volumes[app] / rate_ratio))
                    burst = int(rate * burst_period * 125000)
                    limit = max(int(burst * float(limit_ratio)), 15000)
                    nb_runs = nb_runs + 1
                    print('Run number: ', nb_runs)
                    try:
                        run_proof_of_concept(
                            app, 'eno1', True, '{}mbit'.format(rate), burst, limit, 'skype_back_traces{}'.format(back_dir_idx)
                        )
                        time.sleep(60)
                    except Exception as e:
                        flush_replay_background()
                        time.sleep(300)
                    print('-------------------------------------')

