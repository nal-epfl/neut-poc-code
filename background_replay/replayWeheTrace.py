"""
adapted from code by Zeinab Shmeis (zeinab.shmeis@epfl.ch)

Example:
    python3 replayWeheTrace.py --server --app Youtube_12122018 --server_ip 127.0.0.1
    python3 replayWeheTrace.py --kill_server
    python3 replayWeheTrace.py --client --server_ip=0.0.0.0
"""
import pickle
import sched, argparse
import pandas as pd
from multiprocessing import Process

from python_lib import *

from IOPaths import *
WEHE_REPLAY_TRACES = f'{MAIN_DIR}/background_replay/replayTraces'

SERVER_PORT = 443


def read_wehe_trace(wehe_app):
    print(WEHE_REPLAY_TRACES, wehe_app)
    server_trace_path = os.path.join(WEHE_REPLAY_TRACES, wehe_app, '{}.pcap_server_all.pickle'.format(wehe_app))
    with open(server_trace_path, 'br') as server_pickle:
        server_Q = pickle.load(server_pickle)[0]

    client_trace_path = os.path.join(WEHE_REPLAY_TRACES, wehe_app, '{}.pcap_client_all.json'.format(wehe_app))
    with open(client_trace_path) as json_file:
        client_Q = json.load(json_file)[0]

    cspair = list(server_Q['tcp'].keys())[0]
    response_dfs = []
    for idx, RS in enumerate(server_Q['tcp'][cspair]):
        response_dfs.append(pd.DataFrame({
            'time': [record.timestamp + client_Q[idx]['timestamp'] for record in RS.response_list],
            'payload': [record.payload for record in RS.response_list]
        }))
    server_pkts = pd.concat(response_dfs)

    client_pkts = pd.DataFrame({
        'time': [record['timestamp'] for record in client_Q],
        'payload': [record['payload'] for record in client_Q]
    })
    return client_pkts, server_pkts


def run_server(wehe_app, server_ip="0.0.0.0"):
    print("Start a TCP server")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((server_ip, SERVER_PORT))
    server.listen(10000)

    _, df = read_wehe_trace(wehe_app)

    time.sleep(df["time"].values[0])
    print("Start a server running trace {}".format(wehe_app))

    while True:
        connection, address = server.accept()
        Process(
            target=accept_connection,
            kwargs={"connection": connection, "address": address, "df": df},
        ).start()


def accept_connection(connection, address, df):
    print("Server accepted a connection from {}".format(address))
    send_scheduler = sched.scheduler(time.time, time.sleep)
    for idx, event in df.iterrows():
        send_scheduler.enter(
            event.time,
            1,
            connection.send,
            argument=(bytes.fromhex(event.payload),),
        )

    send_scheduler.run()
    connection.shutdown(socket.SHUT_RDWR)
    connection.close()
    print(f"Finished sending to {address}")


def kill_server():
    try:
        output = subprocess.check_output(
            "fuser {}/{} 2>/dev/null".format(SERVER_PORT, "tcp"), shell=True
        )
        os.system("sudo kill -9 {}".format(int(output)))
    except Exception as e:
        print("NO RUNNING SERVER")


def run_client(wehe_app, server_ip="0.0.0.0"):
    print("Running client")
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect((server_ip, SERVER_PORT))

    df, _ = read_wehe_trace(wehe_app)
    send_scheduler = sched.scheduler(time.time, time.sleep)
    for idx, event in df.iterrows():
        send_scheduler.enter(
            event.time,
            1,
            client_socket.send,
            argument=(bytes.fromhex(event.payload),),
        )

    send_scheduler.run()

    while True:
        data = client_socket.recv(4096)
        if not data:
            break

    client_socket.close()


if __name__ == "__main__":

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--server", action="store_true")
    arg_parser.add_argument("--client", action="store_true")
    arg_parser.add_argument("--server_ip", default="0.0.0.0")
    arg_parser.add_argument("--app")
    arg_parser.add_argument("--kill_server", action="store_true")
    args = arg_parser.parse_args()

    if args.server:
        run_server(args.app, args.server_ip)
    elif args.kill_server:
        kill_server()
    elif args.client:
        run_client(args.app, args.server_ip)
