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

from aws_chiles02.common import get_oid, get_module_name, get_uid, get_session_id, CONTAINER_JAVA_S3_COPY, CONTAINER_CHILES02, make_groups_of_frequencies, FREQUENCY_GROUPS
from aws_chiles02.apps import DockerCopyToS3, DockerClean, DockerCopyAllFromS3Folder
from dfms.drop import DirectoryContainer, dropdict, BarrierAppDROP
from dfms.manager.client import NodeManagerClient, SetEncoder

LOG = logging.getLogger(__name__)


def build_graph(args):
    number_in_chain = len(FREQUENCY_GROUPS) / args.cores
    drop_list = []

    oid01 = get_oid('dir')
    file_drop = ({
        "type": 'plain',
        "storage": 'file',
        "oid": oid01,
        "uid": get_uid(),
        "precious": False,
        "dirname": os.path.join(args.volume, oid01),
        "check_exists": False
    })
    drop_list.append(file_drop)

    outputs = []
    for group in make_groups_of_frequencies(number_in_chain):
        first = True
        end_of_last_element = None
        for frequency_pairs in group:
            copy_from_s3 = dropdict({
                "type": 'app',
                "app": get_module_name(DockerCopyAllFromS3Folder),
                "oid": get_oid('app'),
                "uid": get_uid(),
                "image": CONTAINER_JAVA_S3_COPY,
                "command": 'copy_from_all_from_s3_folder',
                "aws_access_key_id": args.aws_access_key_id,
                "aws_secret_access_key": args.aws_secret_access_key,
                "min_frequency": frequency_pairs[0],
                "max_frequency": frequency_pairs[1],
                "user": 'root'
            })

            oid02 = get_oid('dir')
            measurement_sets = dropdict({
                "type": 'container',
                "container": get_module_name(DirectoryContainer),
                "oid": oid02,
                "uid": get_uid(),
                "precious": False,
                "dirname": os.path.join(args.volume, oid02),
                "check_exists": False
            })

            if first:
                copy_from_s3.addInput(file_drop)
                first = False
            else:
                copy_from_s3.addInput(end_of_last_element)
            copy_from_s3.addOutput(measurement_sets)

            drop_list.append(copy_from_s3)
            drop_list.append(measurement_sets)

            casa_py_drop = dropdict({
                "type": 'app',
                "app": get_module_name(DockerClean),
                "oid": get_oid('app'),
                "uid": get_uid(),
                "image": CONTAINER_CHILES02,
                "command": 'clean',
                "min_frequency": frequency_pairs[0],
                "max_frequency": frequency_pairs[1],
                "user": 'root'
            })
            oid03 = get_oid('dir')
            result = dropdict({
                "type": 'container',
                "container": get_module_name(DirectoryContainer),
                "oid": oid03,
                "uid": get_uid(),
                "precious": False,
                "dirname": os.path.join(args.volume, oid03),
                "check_exists": False,
                "expireAfterUse": True
            })

            casa_py_drop.addInput(measurement_sets)
            casa_py_drop.addOutput(result)

            copy_to_s3 = dropdict({
                "type": 'app',
                "app": get_module_name(DockerCopyToS3),
                "oid": get_oid('app'),
                "uid": get_uid(),
                "image": CONTAINER_JAVA_S3_COPY,
                "command": 'copy_to_s3',
                "user": 'root',
                "min_frequency": frequency_pairs[0],
                "max_frequency": frequency_pairs[1],
                "aws_access_key_id": args.aws_access_key_id,
                "aws_secret_access_key": args.aws_secret_access_key
            })
            s3_drop_out = dropdict({
                "type": 'plain',
                "storage": 's3',
                "oid": get_oid('s3'),
                "uid": get_uid(),
                "expireAfterUse": True,
                "precious": False,
                "bucket": args.bucket,
                "key": 'clean/{0}_{1}/{0}_{1}.tar'.format(
                        frequency_pairs[0],
                        frequency_pairs[1]
                ),
                "aws_access_key_id": args.aws_access_key_id,
                "aws_secret_access_key": args.aws_secret_access_key
            })
            copy_to_s3.addInput(result)
            copy_to_s3.addOutput(s3_drop_out)

            drop_list.append(copy_to_s3)
            drop_list.append(s3_drop_out)
            end_of_last_element = s3_drop_out

        outputs.append(end_of_last_element)

    barrier_drop = dropdict({
        "type": 'app',
        "app": get_module_name(BarrierAppDROP),
        "oid": get_oid('app'),
        "uid": get_uid(),
        "user": 'root'
    })
    drop_list.append(barrier_drop)

    for output in outputs:
        barrier_drop.addInput(output)

    return drop_list, [file_drop['uid']]


def command_json(args):
    drop_list, start_uids = build_graph(args)
    LOG.info(json.dumps(drop_list, indent=2, cls=SetEncoder))


def command_run(args):
    drop_list, start_uids = build_graph(args)

    client = NodeManagerClient(args.host, args.port)

    session_id = get_session_id()
    client.create_session(session_id)
    client.append_graph(session_id, drop_list)
    client.deploy_session(session_id, start_uids)


def parser_arguments():
    parser = argparse.ArgumentParser('Build the CLEAN physical graph for a day')

    subparsers = parser.add_subparsers()

    parser_json = subparsers.add_parser('json', help='display the json')
    parser_json.add_argument('aws_access_key_id', help="the AWS aws_access_key_id to use")
    parser_json.add_argument('aws_secret_access_key', help="the AWS aws_secret_access_key to use")
    parser_json.add_argument('bucket', help='the bucket to access')
    parser_json.add_argument('ms_set', help='the measurement set key')
    parser_json.add_argument('volume', help='the directory on the host to bind to the Docker Apps')
    parser_json.add_argument('cores', type=int, help='the number of cores')
    parser_json.set_defaults(func=command_json)

    parser_run = subparsers.add_parser('run', help='run and deploy')
    parser_run.add_argument('aws_access_key_id', help="the AWS aws_access_key_id to use")
    parser_run.add_argument('aws_secret_access_key', help="the AWS aws_secret_access_key to use")
    parser_run.add_argument('bucket', help='the bucket to access')
    parser_run.add_argument('ms_set', help='the measurement set key')
    parser_run.add_argument('volume', help='the directory on the host to bind to the Docker Apps')
    parser_run.add_argument('cores', type=int, help='the number of cores')
    parser_run.add_argument('host', help='the host the dfms is running on')
    parser_run.add_argument('-p', '--port', type=int, help='the port to bind to', default=8000)
    parser_run.set_defaults(func=command_run)

    args = parser.parse_args()
    return args


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    arguments = parser_arguments()
    arguments.func(arguments)