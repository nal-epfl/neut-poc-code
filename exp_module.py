import random, shutil, socket, json, multiprocessing, time, os, requests, subprocess

from enum import Enum
from multiprocessing import Process
import numpy as np

from IOPaths import *
from td_module import *

import background_replay.replayBackground as backReplay
import test_downloads.downloadTests as testDownloader


# def send_more_replays():
#     time.sleep(random.randint(20, 30))
#     for i in np.arange(5):
#         command = 'cd background_replay; '
#         command += 'for i in {1..10}; do '
#         command += 'python3 replayWeheTrace.py --client --app Youtube_12122018 --server_ip=34.175.251.11 '
#         command += '& done'
#         os.system(command)
#         time.sleep(random.randint(35, 40))
#         os.system("sudo kill -9 $(ps ax | grep replayWehe | awk '{print $1}')")
#         time.sleep(random.randint(0, 3))


################### Wehe Replay Setup ###################
#'probe2skype', 'probewhatsapp', #'probeteams', 'probezoom', 'probe2webex'
class WeheApp(Enum):
    meet = {'name': 'meet', 'protocol': 'udp', 'port': '19305'}
    teams = {'name': 'teams', 'protocol': 'udp', 'port': '3480'}
    skype = {'name': 'skype', 'protocol': 'udp', 'port': '3478'}
    webex = {'name': 'webex', 'protocol': 'udp', 'port': '9000'}
    whatsapp = {'name': 'whatsapp', 'protocol': 'udp', 'port': '49882'}
    zoom = {'name': 'zoom', 'protocol': 'udp', 'port': '8801'}
    twittervideo = {'name': 'twittervideo', 'protocol': 'tcp', 'port': '443'}
    youtube = {'name': 'youtube', 'protocol': 'tcp', 'port': '443'}
    netflix = {'name': 'netflix', 'protocol': 'tcp', 'port': '443'}
    twitch = {'name': 'twitch', 'protocol': 'tcp', 'port': '443'}
    hulu = {'name': 'hulu', 'protocol': 'tcp', 'port': '443'}
    spotify = {'name': 'spotify', 'protocol': 'tcp', 'port': '443'}
    disneyplus = {'name': 'disneyplus', 'protocol': 'tcp', 'port': '443'}
    facebookvideo = {'name': 'facebookvideo', 'protocol': 'tcp', 'port': '443'}
    dailymotion = {'name': 'dailymotion', 'protocol': 'tcp', 'port': '443'}
    deezer = {'name': 'deezer', 'protocol': 'tcp', 'port': '443'}
    nbcsports = {'name': 'nbcsports', 'protocol': 'tcp', 'port': '443'}
    molotovtv = {'name': 'molotovtv', 'protocol': 'tcp', 'port': '443'}
    mycanal = {'name': 'mycanal', 'protocol': 'tcp', 'port': '443'}
    ocs = {'name': 'ocs', 'protocol': 'tcp', 'port': '443'}
    amazon = {'name': 'amazon', 'protocol': 'tcp', 'port': '443'}
    salto = {'name': 'salto', 'protocol': 'tcp', 'port': '443'}
    sfrplay = {'name': 'sfrplay', 'protocol': 'tcp', 'port': '443'}
    vimeo = {'name': 'vimeo', 'protocol': 'tcp', 'port': '443'}
    longtcp = {'name': 'longtcp', 'protocol': 'tcp', 'port': '443'}
    
def get_WeheApp(wehe_app):
    for app in WeheApp:
        if app.name == wehe_app: return app
    return None

    
def load_wehe_cmdline_keys(keys_dir):
    shutil.copy(os.path.join(WEHE_CMDLINE_DIR, 'res', keys_dir, 'main'), os.path.join(WEHE_CMDLINE_DIR, 'res'))
    shutil.copy(os.path.join(WEHE_CMDLINE_DIR, 'res', keys_dir, 'metadata'), os.path.join(WEHE_CMDLINE_DIR, 'res'))
    
class WeheServers:
    def __init__(self):
        self.servers = []
        self.tag = None

class MLabWeheServers(WeheServers):
    def __init__(self):
        self.tag = 'wehe4.meddle.mobi'
        mlab_servers = requests.get('https://siteinfo.mlab-oti.measurementlab.net/v2/sites/hostnames.json').json()
        self.servers = ['{}/24'.format(r['ipv4']) for r in mlab_servers] + ['{}/64'.format(r['ipv6']) for r in mlab_servers]
        load_wehe_cmdline_keys('mlab_keys')
        
class MLabNearestWeheServers(WeheServers):
    def __init__(self):
        self.tag = 'wehe4.meddle.mobi'
        mlab_servers = requests.get('https://locate.measurementlab.net/v2/nearest/wehe/replay').json()
        self.servers = ['{}/24'.format(socket.gethostbyname(record['machine'])) for record in mlab_servers['results']]
        load_wehe_cmdline_keys('mlab_keys')
 
class CustomWeheServers(WeheServers):
    def __init__(self):
        self.tag = 'custom'
        with open(os.path.join(WEHE_CMDLINE_DIR, 'res/servers_ip_list.txt'), 'r') as f:
            self.servers = ['{}/32'.format(ip.rstrip('\n')) for ip in f.readlines()]
        load_wehe_cmdline_keys('custom_keys')


def run_wehe_test(wehe_app, wehe_servers, results_dir='results'):
    os.chdir(WEHE_CMDLINE_DIR)
    command = [
        'java', '-jar', 'wehe-cmdline-4.0.0.jar', 
        '-n', wehe_app,
        '-s', wehe_servers.tag, '-u', '2', 
        '-c', '-r', '{}/'.format(results_dir)]
    subprocess.run(command, timeout=300)
    os.chdir('..')  
################### Background Replay Setup ###################

class BackgroundReplay():
    
    def __init__(self, interface, protocol, remote_clients, traces_dir, traffic_ratio=1):
        # for the server
        self.interface = interface
        self.server_ip = get_ip(self.interface)
        self.protocol = protocol
        # for the remote clients
        with open(os.path.join(BACKGROUND_REPLAY_DIR, 'clients_info.json'), 'r') as f:
            clients_info = json.load(f)
        self.back_clients = [backReplay.RemoteBackClient(clients_info[s]) for s in remote_clients]
        # for the traffic
        self.warmup_time = 10
        self.traffic_dir = self.select_traffic_sample(traces_dir, traffic_ratio)
        
    def start_server(self):
        self.back_process = Process(
            target=backReplay.run_server, kwargs={'server_ip': self.server_ip, 'protocol': self.protocol})
        self.back_process.start()
        print('Background server with ip={} is runing'.format(self.server_ip))
        
    def start_remote_clients(self):
        for back_client in self.back_clients:
            back_client.start_replay(self.traffic_dir, self.server_ip, self.protocol)
        
    def get_client_networks(self):
        return ['{}/32'.format(c.info['ip']) for c in self.back_clients]
    
    def flush(self):
        # kill any background process if exists
        for process in multiprocessing.active_children(): process.kill()

        # kill background server on this machine if it exists
        backReplay.kill_server()

        # kill all clients on the remote machine
        for back_server in self.back_clients:
            back_server.kill_all_clients()
            
    def select_traffic_sample(self, traces_dir, ratio):
        sample_traces_dir = None
        for back_client in self.back_clients:
            sample_traces_dir = back_client.sample_caida_back_from(traces_dir, ratio)
        return sample_traces_dir


################### The Experiment Class ###################

class POCExp:

    def __init__(self, wehe_app, wehe_servers, back_replay, eth_interface, result_dir):
        # app info
        self.wehe_app = wehe_app
        # the servers runing wehe
        self.wehe_servers = wehe_servers
        # the servers running background traffic
        self.back_replay = back_replay
        # the incoming traffic interface (for policing)
        self.eth_interface = eth_interface
        self.tc_policers = []
        self.policing_info = {'policer_type': -1, 'configs': -1}
        # results directory for wehe-cmdline-WeHeY
        self.result_dir = result_dir
        os.makedirs(os.path.join(WEHE_CMDLINE_DIR, self.result_dir), exist_ok=True)

    def set_tc_policer(self, tc_policer):
        self.tc_policers = [tc_policer]
        self.policing_info = {'policer_type': 'general', 'configs': [tc_policer.config.to_json()]}

    def set_common_policer(self, policer_config):#rate, burst_period, limit_ratio):
        target_srcs = np.concatenate([self.back_replay.get_client_networks(), self.wehe_servers.servers])
        self.tc_policers = [TCPolicer(target_srcs, self.eth_interface, 'ifb0', policer_config)]
        self.policing_info = {'policer_type': 'common', 'configs': [policer_config.to_json()]}

    def set_noncommon_policers(self, policer_config):
        back_networks, wehe_networks = self.back_replay.get_client_networks(), self.wehe_servers.servers
        self.tc_policers = [
            TCPolicer(np.array([back_networks[0], wehe_networks[0]]), self.eth_interface, 'ifb0', policer_config, traffic_tag=100),
            TCPolicer(np.array([back_networks[1], wehe_networks[1]]), self.eth_interface, 'ifb1', policer_config, traffic_tag=200),
        ]
        self.policing_info = {'policer_type': 'non-common', 'configs': [policer_config.to_json()]}
        
    def set_different_policers(self, policer_configs, with_back=[True, True]):
        back_networks, wehe_networks = self.back_replay.get_client_networks(), self.wehe_servers.servers
        p1_targets = np.array([back_networks[0], wehe_networks[0]]) if with_back[0] else np.array([wehe_networks[0]])
        p2_targets = np.array([back_networks[1], wehe_networks[1]]) if with_back[1] else np.array([wehe_networks[1]])
        self.tc_policers = [
            TCPolicer(p1_targets, self.eth_interface, 'ifb0', policer_configs[0], traffic_tag=100),
            TCPolicer(p2_targets, self.eth_interface, 'ifb1', policer_configs[1], traffic_tag=200),
        ]
        self.policing_info = {'policer_type': 'different', 'configs': [config.to_json() for config in policer_configs]}

    def run(self):
        # start the policer
        for tc_policer in self.tc_policers:
            tc_policer.enable_policing()

        # start background server
        self.back_replay.flush()
        self.back_replay.start_server()
        print('Do not forget to start the background client replays. Wehe CLI test will start in 1 min.')

        # start background client on the remote machine
        self.back_replay.start_remote_clients()
        time.sleep(self.back_replay.warmup_time)

        # run the wehe test
        try:
            # start tcpdump from client side
            if self.wehe_app.value['protocol'] == 'udp':
                for tc_policer in self.tc_policers:
                    tc_policer.start_tcpdump(os.path.join(WEHE_CMDLINE_DIR, self.result_dir), self.wehe_app.value['port'])

            # start the wehe cli test
            run_wehe_test(wehe_app=self.wehe_app.name, wehe_servers=self.wehe_servers, results_dir=self.result_dir)

            # collect and save info
            wehe_info = testDownloader.get_run_test_info(os.path.join(WEHE_CMDLINE_DIR, self.result_dir))
            test_info = {**wehe_info, 'app': self.wehe_app.name, **self.policing_info, 'background': self.back_replay.traffic_dir}

            output_dir = '{}/{}'.format(TESTS_INFO_DIR, test_info['date'].replace('/', '-'))
            test_file_info = 'test_{}_{}_info.json'.format(test_info['user_id'], test_info['test_id'])
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, test_file_info), 'w') as f:
                json.dump(test_info, f)

            # clean everything
            self.back_replay.flush()
            reset_tc(interface=self.eth_interface)

            # save and clean pcaps
            for tc_policer in self.tc_policers:
                tc_policer.stop_tcpdump(output_dir, '{}_{}'.format(test_info['user_id'], test_info['test_id']))
        except Exception as e:
            self.back_replay.flush()
            reset_tc(interface=self.eth_interface)
            print('failed to record policer configuration because of: ', e)