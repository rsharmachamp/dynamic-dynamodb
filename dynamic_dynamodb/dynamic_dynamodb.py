#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Dynamic DynamoDB

Auto provisioning functionality for Amazon Web Service DynamoDB databases.


APACHE LICENSE 2.0
Copyright 2013 Sebastian Dahlgren

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
import time
import logging
import datetime
import argparse
from boto import dynamodb
from boto.ec2 import cloudwatch


class DynamicDynamoDB:
    """ Class handling connections and scaling """
    cw_connection = None
    ddb_connection = None

    def __init__(self, region, table_name,
                reads_upper_threshold, reads_lower_threshold,
                increase_reads_with, decrease_reads_with,
                writes_upper_threshold, writes_lower_threshold,
                increase_writes_with, decrease_writes_with,
                dry_run=True):
        """ Constructor setting the basic configuration

        :type region: str
        :param region: AWS region to connect to
        :type table_name: str
        :param table_name: DynamoDB table name to use
        :type reads_upper_threshold: int
        :param reads_upper_threshold: Usage percent when we should scale up
        :type reads_lower_threshold: int
        :param reads_lower_threshold: Usage percent when we should scale down
        :type increase_reads_with: int
        :param increase_reads_with: How many percent to scale up reads with
        :type decrease_reads_with: int
        :param decrease_reads_with: How many percent to scale down reads with
        :type writes_upper_threshold: int
        :param writes_upper_threshold: Usage percent when we should scale up
        :type writes_lower_threshold: int
        :param writes_lower_threshold: Usage percent when we should scale down
        :type increase_writes_with: int
        :param increase_writes_with: How many percent to scale up writes with
        :type decrease_writes_with: int
        :param decrease_writes_with: How many percent to scale down writes with
        :type dry_run: bool
        :param dry_run: Set to False if we should make actual changes
        """
        self.region = region
        self.table_name = table_name
        self.reads_upper_threshold = reads_upper_threshold
        self.reads_lower_threshold = reads_lower_threshold
        self.increase_reads_with = increase_reads_with
        self.decrease_reads_with = decrease_reads_with
        self.writes_upper_threshold = writes_upper_threshold
        self.writes_lower_threshold = writes_lower_threshold
        self.increase_writes_with = increase_writes_with
        self.decrease_writes_with = decrease_writes_with
        self.dry_run = dry_run

        #
        # Logging configuration
        #
        self.logger = logging.getLogger('dynamic-dynamodb')
        self.logger.setLevel(logging.DEBUG)
        if self.dry_run:
            stdout_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - DRYRUN - %(levelname)s - %(message)s')
        else:
            stdout_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(stdout_formatter)
        self.logger.addHandler(console_handler)

    def run(self):
        """ Public method for starting scaling """
        try:
            while True:
                self.ensure_proper_provisioning()
                time.sleep(60)
        except KeyboardInterrupt:
            self.logger.info('Caught termination signal. Exiting.')

    def ensure_proper_provisioning(self):
        """ Public method running once to check the current provisioning

        This method is called by run() in order to check provisioning over time
        """
        read_usage = self._get_consumed_reads_percentage()
        write_usage = self._get_consumed_writes_percentage()
        self.logger.info('{0:d}% reads consumed'.format(read_usage))
        self.logger.info('{0:d}% writes consumed'.format(write_usage))

        throughput = {
            'update_needed': False,
            'read_units': self._get_provisioned_read_units(),
            'write_units': self._get_provisioned_write_units()
        }

        # Check if we should update read provisioning
        if read_usage >= self.reads_upper_threshold:
            new_value = self._calculate_increase(
                throughput['read_units'],
                self.increase_reads_with)
            self.logger.debug(
                'Need to update read units to {0:d}%'.format(new_value))
            throughput['update_needed'] = True
            throughput['read_units'] = new_value

        elif read_usage <= self.reads_lower_threshold:
            new_value = self._calculate_decrease(
                throughput['read_units'],
                self.increase_reads_with)
            self.logger.debug(
                'Need to update read units to {0:d}%'.format(new_value))
            throughput['update_needed'] = True
            throughput['read_units'] = new_value

        # Check if we should update write provisioning
        if write_usage >= self.writes_upper_threshold:
            new_value = self._calculate_increase(
                throughput['write_units'],
                self.increase_reads_with)
            self.logger.debug(
                'Need to update write units to {0:d}%'.format(new_value))
            throughput['update_needed'] = True
            throughput['write_units'] = new_value
        elif write_usage <= self.writes_lower_threshold:
            new_value = self._calculate_decrease(
                throughput['write_units'],
                self.increase_reads_with)
            self.logger.debug(
                'Need to update write units to {0:d}%'.format(new_value))
            throughput['update_needed'] = True
            throughput['write_units'] = new_value

        # Handle throughput updates
        if throughput['update_needed']:
            self._update_throughput(
                throughput['read_units'],
                throughput['write_units'])

    def _calculate_decrease(self, original_provisioning, percent):
        """ Decrease the original_provisioning with percent %

        :type original_provisioning: int
        :param original_provisioning: The current provisioning
        :type percent: int
        :param percent: How many percent should we decrease with
        :returns: int -- New provisioning value
        """
        return int(float(original_provisioning)*(float(percent)/100))

    def _calculate_increase(self, original_provisioning, percent):
        """ Increase the original_provisioning with percent %

        :type original_provisioning: int
        :param original_provisioning: The current provisioning
        :type percent: int
        :param percent: How many percent should we increase with
        :returns: int -- New provisioning value
        """
        return int(float(original_provisioning)*(float(percent)/100+1))

    def _ensure_cloudwatch_connection(self):
        """ Make sure that we have a CloudWatch connection """
        if not self.cw_connection:
            self.cw_connection = cloudwatch.connect_to_region(self.region)

    def _ensure_dynamodb_connection(self):
        """ Make sure that we have a CloudWatch connection """
        if not self.ddb_connection:
            self.ddb_connection = dynamodb.connect_to_region(self.region)

    def _get_consumed_reads_percentage(self):
        """ Get the percentage of consumed reads

        :returns: int -- Percentage of consumed reads
        """
        self._ensure_cloudwatch_connection()
        self._ensure_dynamodb_connection()

        table = self.ddb_connection.get_table(self.table_name)

        metrics = self.cw_connection.get_metric_statistics(
            300,
            datetime.datetime.utcnow()-datetime.timedelta(minutes=15),
            datetime.datetime.utcnow()-datetime.timedelta(minutes=10),
            'ConsumedReadCapacityUnits',
            'AWS/DynamoDB',
            ['Sum'],
            dimensions={'TableName': self.table_name},
            unit=None)

        if len(metrics) == 0:
            return 0

        consumed_reads = int(metrics[0]['Sum'])/300
        return int(float(consumed_reads) / float(table.read_units) * 100)

    def _get_consumed_writes_percentage(self):
        """ Get the percentage of consumed writes

        :returns: int -- Percentage of consumed writes
        """
        self._ensure_cloudwatch_connection()
        self._ensure_dynamodb_connection()

        table = self.ddb_connection.get_table(self.table_name)

        metrics = self.cw_connection.get_metric_statistics(
            300,
            datetime.datetime.utcnow()-datetime.timedelta(minutes=15),
            datetime.datetime.utcnow()-datetime.timedelta(minutes=10),
            'ConsumedWriteCapacityUnits',
            'AWS/DynamoDB',
            ['Sum'],
            dimensions={'TableName': self.table_name},
            unit=None)

        if len(metrics) == 0:
            return 0

        consumed_writes = int(metrics[0]['Sum'])/300
        return int(float(consumed_writes) / float(table.read_units) * 100)

    def _get_provisioned_read_units(self):
        """ Get the provisioned read units for the table

        :returns: int -- Provisioned read units
        """
        self._ensure_dynamodb_connection()
        table = self.ddb_connection.get_table(self.table_name)
        return int(table.read_units)

    def _get_provisioned_write_units(self):
        """ Get the provisioned write units for the table

        :returns: int -- Provisioned write units
        """
        self._ensure_dynamodb_connection()
        table = self.ddb_connection.get_table(self.table_name)
        return int(table.write_units)

    def _update_throughput(self, read_units, write_units):
        """ Update throughput on the DynamoDB table

        :type read_units: int
        :param read_units: New read unit provisioning
        :type write_units: int
        :param write_units: New write unit provisioning
        """
        self._ensure_dynamodb_connection()
        table = self.ddb_connection.get_table(self.table_name)
        self.logger.info(
            'Updating read provisioning to: {0:d}'.format(read_units))
        self.logger.info(
            'Updating write provisioning to: {0:d}'.format(write_units))
        if False:
            table.update_throughput(int(read_units, int(write_units)))


def main():
    """ Main function handling option parsing etc """
    parser = argparse.ArgumentParser(
        description='Dynamic DynamoDB - Auto provisioning AWS DynamoDB')
    parser.add_argument('--dry-run',
        action='store_true',
        help='Run without making any changes to your DynamoDB database')
    dynamodb_ag = parser.add_argument_group('DynamoDB settings')
    dynamodb_ag.add_argument('-r', '--region',
        default='us-east-1',
        help='AWS region to operate in'),
    dynamodb_ag.add_argument('-t', '--table-name',
        required=True,
        help='How many percent should we decrease the read units with?')
    r_scaling_ag = parser.add_argument_group('Read units scaling properties')
    r_scaling_ag.add_argument('--reads-upper-threshold',
        default=90,
        type=int,
        help="""\
Scale up the reads with --increase-reads-with percent if the currently
consumed read units reaches this many percent""")
    r_scaling_ag.add_argument('--reads-lower-threshold',
        default=30,
        type=int,
        help="""\
Scale down the reads with --decrease-reads-with percent if the currently
consumed read units is as low as this percentage""")
    r_scaling_ag.add_argument('--increase-reads-with',
        default=50,
        type=int,
        help='How many percent should we increase the read units with?')
    r_scaling_ag.add_argument('--decrease-reads-with',
        default=50,
        type=int,
        help='How many percent should we decrease the read units with?')
    w_scaling_ag = parser.add_argument_group('Write units scaling properties')
    w_scaling_ag.add_argument('--writes-upper-threshold',
        default=90,
        type=int,
        help="""\
Scale up the writes with --increase-writes-with percent if the currently
consumed write units reaches this many percent""")
    w_scaling_ag.add_argument('--writes-lower-threshold',
        default=30,
        type=int,
        help="""\
Scale down the writes with --decrease-writes-with percent if the currently
consumed write units is as low as this percentage""")
    w_scaling_ag.add_argument('--increase-writes-with',
        default=50,
        type=int,
        help='How many percent should we increase the write units with?')
    w_scaling_ag.add_argument('--decrease-writes-with',
        default=50,
        type=int,
        help='How many percent should we decrease the write units with?')
    args = parser.parse_args()

    dynamic_ddb = DynamicDynamoDB(
        args.region,
        args.table_name,
        args.reads_upper_threshold,
        args.reads_lower_threshold,
        args.increase_reads_with,
        args.decrease_reads_with,
        args.writes_upper_threshold,
        args.writes_lower_threshold,
        args.increase_writes_with,
        args.decrease_writes_with,
        args.dry_run)
    dynamic_ddb.run()

if __name__ == '__main__':
    main()