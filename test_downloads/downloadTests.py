"""
by: Zeinab Shmeis (zeinab.shmeis@epfl.ch)

Example:
    python3 downloadTests.py --process_results_info --result_dir=./results --output_dir=./tests_info_dir
    python3 downloadTests.py --start_gc_cli
    python3 downloadTests.py --download_test --test_info_file=./tests_info_dir/2022-07-23/test_@ucxaft95e_4_info.json --output_dir=./tests_result_dir
    python3 downloadTests.py --download_all_tests --tests_info_dir=./tests_info_dir/2022-07-23 --output_dir=./tests_result_dir
"""

import os, shutil, json, re, argparse
from IOPaths import *


class WeheTestResult:
    def __init__(self, test_dir, replayInfo_filename):
        self.replayInfo_file = '{}/replayInfo/{}'.format(test_dir, replayInfo_filename)
        self.metaInfo = self.parse_replayInfo_file()

        self.pcap_file_o = '{}/tcpdumpsResults/dump_server_{}_{}_{}_{}_0_out.pcap'.format(
            test_dir, self.metaInfo['clientId'], self.metaInfo['suspectedApp'], self.metaInfo['testType'], self.metaInfo['testCount']
        )
        self.pcap_file_r = '{}/tcpdumpsResults/dump_server_{}_{}_{}_{}_1_out.pcap'.format(
            test_dir, self.metaInfo['clientId'], self.metaInfo['controlApp'], self.metaInfo['testType'], self.metaInfo['testCount']
        )
        self.xput_file_o = '{}/clientXputs/Xput_{}_{}_0.json'.format(test_dir, self.metaInfo['clientId'], self.metaInfo['testCount'])
        self.xput_file_r = '{}/clientXputs/Xput_{}_{}_1.json'.format(test_dir, self.metaInfo['clientId'], self.metaInfo['testCount'])
        self.result_file = '{}/decisions/results_{}_Client_{}_1.json'.format(test_dir, self.metaInfo['clientId'], self.metaInfo['testCount'])

    def parse_replayInfo_file(self):
        with open(self.replayInfo_file) as json_file:
            info_json = json.load(json_file)
            app = info_json[4].replace('Random', '')
            if not re.match('[a-zA-Z]+-[0-9]+', app): return []
            return {
                'clientId': info_json[1],
                'controlApp': '{}Random-{}'.format(*app.split('-')),
                'suspectedApp': app,
                'testType': info_json[5],
                'testCount': info_json[6],
                'testId': info_json[7],
            }

    def copy_to(self, dst_dir):
        try:
            shutil.copy(self.replayInfo_file, dst_dir)
            shutil.copy(self.pcap_file_o, dst_dir)
            shutil.copy(self.pcap_file_r, dst_dir)
            shutil.copy(self.xput_file_o, dst_dir)
            shutil.copy(self.xput_file_r, dst_dir)
            shutil.copy(self.result_file, dst_dir)
        except Exception as e:
            print('Failed to copy test files: {}'.format(e))

    
def start_google_cloud_cli():
    os.system('{}/bin/gcloud init'.format(GOOGLE_CLOUD_SDK_DIR))
    
    
def find_test_files_per_server(user_id, test_id, server, date, output_dir):
    temp_dir = '{}/temp_dir'.format(output_dir)
    os.makedirs(temp_dir, exist_ok=True)
    os.system('{}/bin/gsutil -m cp -r gs://archive-measurement-lab/wehe/replay/{}/*-replay-{}-wehe.tgz {}/'.format(GOOGLE_CLOUD_SDK_DIR, date, server, temp_dir))

    for tar_file in os.listdir(temp_dir):
        if not ('.tgz' in tar_file): continue
        os.system('tar xzvf {}/{} --directory {}'.format(temp_dir, tar_file, temp_dir))
        for case in os.listdir('{}/{}'.format(temp_dir, date)):
            if not (case == user_id): continue
            case_dir = '{}/{}/{}'.format(temp_dir, date, case)
            try:
                for replay_file in os.listdir('{}/replayInfo'.format(case_dir)):
                    wehe_test = WeheTestResult(case_dir, replay_file)
                    if (wehe_test.metaInfo['clientId'] == user_id) and (wehe_test.metaInfo['testCount'] == test_id):
                        dst_dir = '{}/{}'.format(output_dir, server)
                        os.makedirs(dst_dir, exist_ok=True)
                        wehe_test.copy_to(dst_dir)
            except Exception as e:
                print(e)
            shutil.rmtree('{}/2022'.format(temp_dir))
            
    shutil.rmtree(temp_dir)


def download_test_files(test_info_file, output_dir):
    print('download test {}'.format(test_info_file))
    with open(test_info_file) as json_file: info = json.load(json_file)
    date, user_id, test_id = info['date'], info['user_id'], info['test_id']
    result_dir = '{}/{}/{}_{}'.format(output_dir, date.replace('/', '-'), user_id, test_id)
    find_test_files_per_server(user_id, test_id, info['servers'][0], date, result_dir)
    find_test_files_per_server(user_id, test_id, info['servers'][1], date, result_dir)
    shutil.copy(test_info_file, result_dir)
    

def download_all_tests_in_directory(tests_info_dir, output_dir):
    for test_info in os.listdir(tests_info_dir):
        try:
            download_test_files('{}/{}'.format(tests_info_dir, test_info), output_dir)
        except Exception as e:
            print('Failed to download test {}: {}'.format(test_info, e))


def process_run_test_info(test_result_dir, output_dir):
    try:
        test_info = get_run_test_info(test_result_dir)
        output_dir = '{}/{}'.format(output_dir, test_info['date'].replace('/', '-'))
        os.makedirs(output_dir, exist_ok=True)
        with open('{}/test_{}_{}_info.json'.format(output_dir, test_info['user_id'], test_info['test_id']), 'w') as f:
            json.dump(test_info, f)
    except Exception as e:
        print('Failed to process run results: {}'.format(e))


def get_run_test_info(test_result_dir):
    try:
        with open('{}/info.txt'.format(test_result_dir), 'r') as f:
            user_id, test_id = [val.rstrip('\n') for val in f.readlines()]

        servers = []
        with open('{}/logs/logs_{}_{}_0.txt'.format(test_result_dir, user_id, test_id)) as f:
            lines = f.readlines()
            date, time = lines[0].split(' ')[0:2]
            for line in lines:
                if 'Connected to socket' in line:
                    str_match = re.search('wss://wehe-(.+?)\.mlab-oti\.measurement-lab\.org', line)
                    if str_match: servers.append(str_match.group(1))

        return {'user_id': user_id, 'test_id': test_id, 'servers': servers, 'date': date, 'time': time}
    except Exception as e:
        print('Failed to process run results: {}'.format(e))


if __name__ == '__main__':
    
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--process_results_info', action='store_true')
    arg_parser.add_argument('--start_gc_cli', action='store_true')
    arg_parser.add_argument('--download_test', action='store_true')
    arg_parser.add_argument('--download_all_tests', action='store_true')
    arg_parser.add_argument('--result_dir')
    arg_parser.add_argument('--output_dir')
    arg_parser.add_argument('--test_info_file')
    arg_parser.add_argument('--tests_info_dir')
    args = arg_parser.parse_args()

    if args.process_results_info:
        process_run_test_info(args.result_dir, args.output_dir)
    elif args.start_gc_cli:
        start_google_cloud_cli()
    elif args.download_test:
        download_test_files(args.test_info_file, args.output_dir)
    elif args.download_all_tests:
        download_all_tests_in_directory(args.tests_info_dir, args.output_dir)

