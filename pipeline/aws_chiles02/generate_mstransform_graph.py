#
#    ICRAR - International Centre for Radio Astronomy Research
#    (c) UWA - The University of Western Australia
#    Copyright by UWA (in the framework of the ICRAR)
#    All rights reserved
#
#    This library is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation; either
#    version 2.1 of the License, or (at your option) any later version.
#
#    This library is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with this library; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston,
#    MA 02111-1307  USA
#
"""
Build a dictionary for the execution graph
"""
import argparse
import json
import logging
import os

import boto3
import time
from configobj import ConfigObj

from aws_chiles02.build_graph import BuildGraph
from aws_chiles02.common import get_session_id, get_list_frequency_groups, FrequencyPair, get_argument, get_user_data, get_aws_credentials, get_file_contents, MeasurementSetData, get_uuid
from aws_chiles02.ec2_controller import EC2Controller
from aws_chiles02.settings_file import AWS_REGION, AWS_AMI_ID, SIZE_1GB
from dfms.manager.client import NodeManagerClient, SetEncoder

LOG = logging.getLogger(__name__)
QUEUE = 'startup_complete'


class WorkToDo:
    def __init__(self, width, bucket_name, s3_split_name):
        self._width = width
        self._bucket_name = bucket_name
        self._s3_split_name = s3_split_name
        self._work_already_done = None
        self._bucket = None
        self._list_frequencies = None
        self._work_to_do = {}

    def calculate_work_to_do(self):
        session = boto3.Session(profile_name='aws-chiles02')
        s3 = session.resource('s3', use_ssl=False)

        list_measurement_sets = []
        self._bucket = s3.Bucket(self._bucket_name)
        for key in self._bucket.objects.all():
            if key.key.endswith('_calibrated_deepfield.ms.tar'):
                obj = s3.Object(key.bucket_name, key.key)
                storage_class = obj.storage_class
                restore = obj.restore
                LOG.info('{0}, {1}, {2}'.format(key.key, storage_class, restore))

                ok_to_queue = True
                if 'GLACIER' == storage_class:
                    if restore is None or restore.startswith('ongoing-request="true"'):
                        ok_to_queue = False

                if ok_to_queue:
                    list_measurement_sets.append(MeasurementSetData(key.key, key.size))

        # Get work we've already done
        self._list_frequencies = get_list_frequency_groups(self._width)
        self._work_already_done = self._get_work_already_done()

        for day_to_process in list_measurement_sets:
            day_work_already_done = self._work_already_done.get(day_to_process.short_name)
            list_frequency_groups = self._get_details_for_measurement_set(day_work_already_done)

            if self._ignore_day(list_frequency_groups):
                LOG.info('{0} has already been process.'.format(day_to_process.full_tar_name))
            else:
                self._work_to_do[day_to_process] = list_frequency_groups

    def _get_work_already_done(self):
        frequencies_per_day = {}
        for key in self._bucket.objects.filter(Prefix=self._s3_split_name):
            elements = key.key.split('/')

            day_key = elements[2]
            # Remove the .tar
            day_key = day_key[:-4]

            frequencies = frequencies_per_day.get(day_key)
            if frequencies is None:
                frequencies = []
                frequencies_per_day[day_key] = frequencies

            frequencies.append(elements[1])

        return frequencies_per_day

    def _get_details_for_measurement_set(self, splits_done):
        frequency_groups = []
        if splits_done is None:
            frequency_groups.extend(self._list_frequencies)
        else:
            # Remove the groups we've processed
            for frequency_group in self._list_frequencies:
                if frequency_group.name not in splits_done:
                    frequency_groups.append(frequency_group)

        return frequency_groups

    def _ignore_day(self, list_frequency_groups):
        if len(list_frequency_groups) >= 4:
            return False

        # Check if we have the first groups
        count_bottom = 0
        for bottom_frequency in range(940, 952, self._width):
            frequency_group = FrequencyPair(bottom_frequency, bottom_frequency + self._width)
            if frequency_group in list_frequency_groups:
                count_bottom += 1

        return len(list_frequency_groups) - count_bottom <= 0

    @property
    def work_to_do(self):
        return self._work_to_do


def get_s3_split_name(width):
    return 'split_{}'.format(width)


def get_node_manager_user_data(boto_data, uuid):
    cloud_init = get_file_contents('dfms_cloud_init.yaml')
    cloud_init_dynamic = '''#cloud-config
# Write the boto file
write_files:
  - path: "/root/.aws/credentials"
    permissions: "0544"
    owner: "root"
    content: |
      [{0}]
      aws_access_key_id = {1}
      aws_secret_access_key = {2}
  - path: "/home/ec2-user/.aws/credentials"
    permissions: "0544"
    owner: "ec2-user:ec2-user"
    content: |
      [{0}]
      aws_access_key_id = {1}
      aws_secret_access_key = {2}
'''.format(
            'aws-chiles02',
            boto_data[0],
            boto_data[1],
    )
    user_script = get_file_contents('node_manager_start_up.bash')
    dynamic_script = '''#!/bin/bash -vx
runuser -l ec2-user -c 'cd /home/ec2-user/aws-chiles02/pipeline/aws_chiles02 && source /home/ec2-user/virtualenv/aws-chiles02/bin/activate && python startup_complete.py {1} us-west-2 "{0}"' '''\
            .format(uuid, QUEUE)
    user_data = get_user_data([cloud_init, cloud_init_dynamic, user_script, dynamic_script])
    return user_data


def get_data_island_manager_user_data(boto_data, uuid):
    cloud_init = get_file_contents('dfms_cloud_init.yaml')
    cloud_init_dynamic = '''#cloud-config
# Write the boto file
write_files:
  - path: "/root/.aws/credentials"
    permissions: "0544"
    owner: "root"
    content: |
      [{0}]
      aws_access_key_id = {1}
      aws_secret_access_key = {2}
  - path: "/home/ec2-user/.aws/credentials"
    permissions: "0544"
    owner: "ec2-user:ec2-user"
    content: |
      [{0}]
      aws_access_key_id = {1}
      aws_secret_access_key = {2}
'''.format(
        'aws-chiles02',
        boto_data[0],
        boto_data[1],
    )
    user_script = get_file_contents('island_manager_start_up.bash')
    dynamic_script = '''#!/bin/bash -vx
runuser -l ec2-user -c 'cd /home/ec2-user/aws-chiles02/pipeline/aws_chiles02 && source /home/ec2-user/virtualenv/aws-chiles02/bin/activate && python startup_complete.py {1} us-west-2 "{0}"' ''' \
        .format(uuid, QUEUE)
    user_data = get_user_data([cloud_init, cloud_init_dynamic, user_script, dynamic_script])
    return user_data


def get_nodes_required(days, days_per_node, spot_price1, spot_price2):
    nodes = []
    counts = [0, 0]
    for day in days:
        if day.size <= 500 * SIZE_1GB:
            counts[0] += 1
        else:
            counts[1] += 1

    node_count = 0
    if counts[0] > 0:
        count = max(counts[0] / days_per_node, 1)
        node_count += count
        nodes.append({
            'number_instances': count,
            'instance_type': 'i2.2xlarge',
            'spot_price': spot_price1
        })
    if counts[1] > 0:
        count = max(counts[1] / days_per_node, 1)
        node_count += count
        nodes.append({
            'number_instances': count,
            'instance_type': 'i2.4xlarge',
            'spot_price': spot_price2
        })

    return nodes, node_count


def get_reported_running(uuid, count, wait=600):
    session = boto3.Session(profile_name='aws-chiles02')
    sqs = session.resource('sqs', region_name=AWS_REGION)
    queue = sqs.get_queue_by_name(QueueName=QUEUE)
    nodes_running = {}
    stop_time = time.time() + wait
    messages_received = 0
    while time.time() <= stop_time and count < messages_received:
        for message in queue.receive_messages(MessageAttributeNames=['uuid']):
            if message.message_attributes is not None:
                message_uuid = message.message_attributes.get('uuid').get('StringValue')
                if message_uuid == uuid:
                    json_message = message.body
                    message_details = json.loads(json_message)

                    ip_addresses = nodes_running.get(message_details['instance_type'])
                    if ip_addresses is None:
                        ip_addresses = []
                        nodes_running[message_details['instance_type']] = ip_addresses
                    ip_addresses.append(message_details['ip_address'])
                    LOG.info('{0} - {1} has started successfully'.format(message_details['ip_address'], message_details['instance_type']))
                    messages_received += 1
                    message.delete()

        time.sleep(15)

    return nodes_running


def create_and_generate(bucket_name, frequency_width, ami_id, spot_price1, spot_price2, volume, days_per_node, add_shutdown):
    boto_data = get_aws_credentials('aws-chiles02')
    if boto_data is not None:

        work_to_do = WorkToDo(frequency_width, bucket_name, get_s3_split_name(frequency_width))
        work_to_do.calculate_work_to_do()

        days = work_to_do.work_to_do.keys()
        nodes_required, node_count = get_nodes_required(days, days_per_node, spot_price1, spot_price2)

        if len(nodes_required) > 0:
            uuid = get_uuid()
            ec2_data = EC2Controller(
                ami_id,
                nodes_required,
                get_node_manager_user_data(boto_data, uuid),
                AWS_REGION,
                tags=[
                    {
                        'Key': 'Owner',
                        'Value': 'Kevin',
                    },
                    {
                        'Key': 'Name',
                        'Value': 'DFMS Node',
                    },
                    {
                        'Key': 'uuid',
                        'Value': uuid,
                    }
                ]

            )
            ec2_data.start_instances()

            reported_running = get_reported_running(
                uuid,
                node_count,
                wait=600
            )

            # Create the Data Island Manager
            uuid = get_uuid()
            data_island_manager = EC2Controller(
                ami_id,
                [
                    {
                        'number_instances': 1,
                        'instance_type': 'm4.large',
                        'spot_price': spot_price1
                    }
                ],
                get_data_island_manager_user_data(boto_data, uuid),
                AWS_REGION,
                tags=[
                    {
                        'Key': 'Owner',
                        'Value': 'Kevin',
                    },
                    {
                        'Key': 'Name',
                        'Value': 'Data Island Manager',
                    },
                    {
                        'Key': 'uuid',
                        'Value': uuid,
                    }
                ]
            )
            data_island_manager.start_instances()
            data_island_manager_running = get_reported_running(
                uuid,
                1,
                wait=600
            )

            if len(data_island_manager_running['i2.xlarge']) == 1:
                # Now build the graph
                graph = BuildGraph(work_to_do.work_to_do, bucket_name, volume, 7, reported_running, add_shutdown, frequency_width)
                graph.build_graph()

                client = NodeManagerClient(data_island_manager_running['m4.large'][0], 8001)

                session_id = get_session_id()
                client.create_session(session_id)
                client.append_graph(session_id, graph.drop_list)
                client.deploy_session(session_id, graph.start_oids)
    else:
        LOG.error('Unable to find the AWS credentials')


def use_and_generate():
    pass


def command_json(args):
    work_to_do = WorkToDo(args.width, args.bucket, get_s3_split_name(args.width))
    work_to_do.calculate_work_to_do()

    node_details = {
        'i2.2xlarge': ['node_{0}'.format(i) for i in range(0, args.nodes)]
    }
    graph = BuildGraph(work_to_do.work_to_do, args.bucket, args.volume, args.parallel_streams, node_details, args.shutdown, args.width)
    graph.build_graph()
    json_dumps = json.dumps(graph.drop_list, indent=2, cls=SetEncoder)
    LOG.info(json_dumps)
    with open("/tmp/json_split.txt", "w") as json_file:
        json_file.write(json_dumps)


def command_create(args):
    create_and_generate(
        args.bucket,
        args.width,
        args.ami,
        args.spot_price1,
        args.spot_price2,
        args.volume,
        args.days_per_node,
        args.shutdown,
    )


def command_use(args):
    use_and_generate(

    )


def command_interactive(args):
    LOG.info(args)
    path_dirname, filename = os.path.split(__file__)
    root, ext = os.path.splitext(filename)
    config_file_name = '{0}/{1}.settings'.format(path_dirname, root)
    if os.path.exists(config_file_name):
        config = ConfigObj(config_file_name)
    else:
        config = ConfigObj()
        config.filename = config_file_name

    get_argument(config, 'create_use', 'Create or use', allowed=['create', 'use'], help_text='the use a network or create a network')
    if config['create_use'] == 'create':
        get_argument(config, 'ami', 'AMI Id', help_text='the AMI to use', default=AWS_AMI_ID)
        get_argument(config, 'spot_price1', 'Spot Price for i2.2xlarge', help_text='the spot price')
        get_argument(config, 'spot_price2', 'Spot Price for i2.4xlarge', help_text='the spot price')
        get_argument(config, 'bucket_name', 'Bucket name', help_text='the bucket to access', default='13b-266')
        get_argument(config, 'volume', 'Volume', help_text='the directory on the host to bind to the Docker Apps')
        get_argument(config, 'width', 'Frequency width', data_type=int, help_text='the frequency width', default=4)
        get_argument(config, 'days_per_node', 'Number of days per node', data_type=int, help_text='the number of days per node', default=1)
        get_argument(config, 'shutdown', 'Add the shutdown node', data_type=bool, help_text='add a shutdown drop', default=True)
    else:
        get_argument(config, 'dim', 'Data Island Manager', help_text='the IP to the DataIsland Manager')
        get_argument(config, 'bucket_name', 'Bucket name', help_text='the bucket to access', default='13b-266')
        get_argument(config, 'volume', 'Volume', help_text='the directory on the host to bind to the Docker Apps')
        get_argument(config, 'width', 'Frequency width', data_type=int, help_text='the frequency width', default=4)
        get_argument(config, 'shutdown', 'Add the shutdown node', data_type=bool, help_text='add a shutdown drop', default=True)

    # Write the arguments
    config.write()

    # Run the command
    if config['create_use'] == 'create':
        create_and_generate(
            config['bucket_name'],
            config['width'],
            config['ami'],
            config['spot_price1'],
            config['spot_price2'],
            config['volume'],
            config['days_per_node'],
            config['shutdown'],
        )
    else:
        use_and_generate(

        )


def parser_arguments():
    parser = argparse.ArgumentParser('Build the MSTRANSFORM physical graph for a day')

    subparsers = parser.add_subparsers()

    parser_json = subparsers.add_parser('json', help='display the json')
    parser_json.add_argument('bucket', help='the bucket to access')
    parser_json.add_argument('volume', help='the directory on the host to bind to the Docker Apps')
    parser_json.add_argument('parallel_streams', type=int, help='the of parallel streams')
    parser_json.add_argument('-w', '--width', type=int, help='the frequency width', default=4)
    parser_json.add_argument('-n', '--nodes', type=int, help='the number of nodes', default=1)
    parser_json.add_argument('-s', '--shutdown', action="store_true", help='add a shutdown drop')
    parser_json.set_defaults(func=command_json)

    parser_create = subparsers.add_parser('create', help='run and deploy')
    parser_create.add_argument('ami', help='the ami to use')
    parser_create.add_argument('spot_price1', type=float, help='the spot price')
    parser_create.add_argument('spot_price2', type=float, help='the spot price')
    parser_create.add_argument('bucket', help='the bucket to access')
    parser_create.add_argument('volume', help='the directory on the host to bind to the Docker Apps')
    parser_create.add_argument('-w', '--width', type=int, help='the frequency width', default=4)
    parser_create.add_argument('-d', '--days_per_node', type=int, help='the number of days per node', default=1)
    parser_create.add_argument('-s', '--shutdown', action="store_true", help='add a shutdown drop')
    parser_create.set_defaults(func=command_create)

    parser_use = subparsers.add_parser('use', help='use what is running and deploy')
    parser_use.add_argument('bucket', help='the bucket to access')
    parser_use.add_argument('volume', help='the directory on the host to bind to the Docker Apps')
    parser_use.add_argument('host', help='the host the dfms is running on')
    parser_use.add_argument('-p', '--port', type=int, help='the port to bind to', default=8001)
    parser_use.add_argument('-w', '--width', type=int, help='the frequency width', default=4)
    parser_use.add_argument('-s', '--shutdown', action="store_true", help='add a shutdown drop')
    parser_use.set_defaults(func=command_use)

    parser_interactive = subparsers.add_parser('interactive', help='prompt the user for parameters and then run')
    parser_interactive.set_defaults(func=command_interactive)

    args = parser.parse_args()
    return args


if __name__ == '__main__':
    # json 13b-266 /mnt/dfms/dfms_root 8 -w 8 -s
    # interactive
    logging.basicConfig(level=logging.INFO)
    arguments = parser_arguments()
    arguments.func(arguments)
