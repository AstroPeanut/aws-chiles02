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
Retrieve measurement sets from glacier
"""
import argparse
import logging

import boto3

from aws_chiles02.common import bytes2human

LOG = logging.getLogger(__name__)
logging.getLogger('boto3').setLevel(logging.INFO)
logging.getLogger('botocore').setLevel(logging.INFO)
logging.getLogger('nose').setLevel(logging.INFO)
logging.getLogger('s3transfer').setLevel(logging.INFO)


def parser_arguments():
    parser = argparse.ArgumentParser('Size of files in Bucket')
    parser.add_argument('bucket', help='the s3 bucket')

    args = parser.parse_args()
    LOG.info(args)
    return args


def retrieve_files(args):
    session = boto3.Session(profile_name='aws-chiles02')
    s3 = session.resource('s3')

    bucket = s3.Bucket(args.bucket)
    size = 0
    for key in bucket.objects.all():
        size += key.size
        LOG.info('{0}, {1}, {2}, {3}'.format(key.key, bytes2human(key.size), size, bytes2human(size)))

    LOG.info('Size = {0}'.format(bytes2human(size)))

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    arguments = parser_arguments()
    retrieve_files(arguments)