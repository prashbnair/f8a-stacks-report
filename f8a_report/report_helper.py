"""Various utility functions used across the repo."""

import os
import json
import logging
import datetime
import psycopg2
import psycopg2.extras
import itertools
import boto3
from psycopg2 import sql

logger = logging.getLogger(__file__)


class Postgres:
    """Postgres connection session handler."""

    def __init__(self):
        """Initialize the connection to Postgres database."""
        conn_string = "host='{host}' dbname='{dbname}' user='{user}' password='{password}'".\
            format(host=os.getenv('PGBOUNCER_SERVICE_HOST', 'bayesian-pgbouncer'),
                   dbname=os.getenv('POSTGRESQL_DATABASE', 'coreapi'),
                   user=os.getenv('POSTGRESQL_USER', 'coreapi'),
                   password=os.getenv('POSTGRESQL_PASSWORD', 'coreapi'))
        self.conn = psycopg2.connect(conn_string)
        self.cursor = self.conn.cursor()


class S3Helper:
    """Helper class for storing reports to S3."""

    def __init__(self):
        """Init method for the helper class."""
        self.region_name = os.environ.get('AWS_S3_REGION') or 'us-east-1'
        self.aws_s3_access_key = os.environ.get('AWS_S3_ACCESS_KEY_ID')
        self.aws_s3_secret_access_key = os.environ.get('AWS_S3_SECRET_ACCESS_KEY')
        self.deployment_prefix = os.environ.get('DEPLOYMENT_PREFIX') or 'dev'
        self.report_bucket_name = os.environ.get('REPORT_BUCKET_NAME')

        if self.aws_s3_secret_access_key is None or self.aws_s3_access_key is None or\
                self.region_name is None or self.deployment_prefix is None:
            raise ValueError("AWS credentials or S3 configuration was "
                             "not provided correctly. Please set the AWS_S3_REGION, "
                             "AWS_S3_ACCESS_KEY_ID, AWS_S3_SECRET_ACCESS_KEY, REPORT_BUCKET_NAME "
                             "and DEPLOYMENT_PREFIX correctly.")
        # S3 endpoint URL is required only for local deployments
        self.s3_endpoint_url = os.environ.get('S3_ENDPOINT_URL') or 'http://localhost'

        self.s3 = boto3.resource('s3', region_name=self.region_name,
                                 aws_access_key_id=self.aws_s3_access_key,
                                 aws_secret_access_key=self.aws_s3_secret_access_key)

    def store_json_content(self, content, start_date, end_date, frequency='weekly'):
        """Store the report content to the S3 storage."""
        try:
            if self.frequency == 'weekly':
                filename = '{start}to{end}.json'.format(start=start_date, end=end_date)
            elif self.frequency == 'monthly':
                filename = '{}.json'.format(datetime.datetime.strptime('2019-01-31', '%Y-%m-%d').
                                            strftime('%Y-%m'))
            else:
                filename = 'dummy-{start}to{end}.json'.format(start=start_date, end=end_date)

            bucket_key = '{dirname}/{freq}/{filename}'.format(dirname=self.deployment_prefix,
                                                              freq=frequency, filename=filename)
            self.s3.Object(self.report_bucket_name, bucket_key).put(Body=json.dumps(
                                                                content, indent=2).encode('utf-8'))
        except Exception as e:
            logger.exception('%r' % e)


class ReportHelper:
    """Stack Analyses report helper functions."""

    def __init__(self):
        """Init method for the Report helper class."""
        self.s3 = S3Helper()
        self.pg = Postgres()
        self.conn = self.pg.conn
        self.cursor = self.pg.cursor

    def validate_and_process_date(self, some_date):
        """Validate the date format and apply the format YYYY-MM-DDTHH:MI:SSZ."""
        try:
            datetime.datetime.strptime(some_date, '%Y-%m-%d')
        except ValueError:
            raise ValueError("Incorrect data format, should be YYYY-MM-DD")
        return some_date

    def retrieve_stack_analyses_ids(self, start_date, end_date):
        """Retrieve results for stack analyses requests."""
        try:
            start_date = self.validate_and_process_date(start_date)
            end_date = self.validate_and_process_date(end_date)
        except ValueError:
            raise "Invalid date format"

        # Avoiding SQL injection
        query = sql.SQL('SELECT {} FROM {} WHERE {} BETWEEN \'%s\' AND \'%s\'').format(
            sql.Identifier('id'), sql.Identifier('stack_analyses_request'),
            sql.Identifier('submitTime')
        )

        self.cursor.execute(query.as_string(self.conn) % (start_date, end_date))
        rows = self.cursor.fetchall()

        id_list = []
        for row in rows:
            for col in row:
                id_list.append(col)

        return id_list

    def flatten_list(self, alist):
        """Convert a list of lists to a single list."""
        return list(itertools.chain.from_iterable(alist))

    def datediff_in_millisecs(self, start_date, end_date):
        """Return the difference of two datetime strings in milliseconds."""
        format = '%Y-%m-%dT%H:%M:%S.%f'
        return (datetime.datetime.strptime(end_date, format) -
                datetime.datetime.strptime(start_date, format)).microseconds / 1000

    def populate_key_count(self, in_list=[]):
        """Generate a dict with the frequency of list elements."""
        out_dict = {}
        try:
            for item in in_list:
                if item in out_dict:
                    out_dict[item] += 1
                else:
                    out_dict[item] = 1
        except (IndexError, KeyError, TypeError) as e:
            logger.exception('Error: %r' % e)
            return {}
        return out_dict

    def set_unique_stack_deps_count(self, unique_stacks_with_recurrence_count):
        """Set the dependencies count against the identified unique stacks."""
        out_dict = {}
        for key in unique_stacks_with_recurrence_count.items():
            new_dict = {}
            for stack in key[1].items():
                new_dict[stack[0]] = len(stack[0].split(','))
            out_dict[key[0]] = new_dict
        return out_dict

    def normalize_deps_list(self, deps):
        """Flatten the dependencies dict into a list."""
        normalized_list = []
        for dep in deps:
            normalized_list.append('{package} {version}'.format(package=dep['package'],
                                                                version=dep['version']))
        return sorted(normalized_list)

    def normalize_worker_data(self, start_date, end_date, stack_data, worker, frequency='weekly'):
        """Normalize worker data for reporting."""
        total_stack_requests = {'all': 0, 'npm': 0, 'maven': 0}

        stack_data = json.loads(stack_data)
        template = {
            'report': {
                'from': start_date,
                'to': end_date,
                'generated_on': datetime.datetime.now().isoformat('T')
            },
            'stacks_summary': {},
            'stacks_details': []
        }
        all_deps = {'npm': [], 'maven': []}
        all_unknown_deps = {'npm': [], 'maven': []}
        all_unknown_lic = []
        all_cve_list = []

        total_response_time = {'all': 0.0, 'npm': 0.0, 'maven': 0.0}
        if worker == 'stack_aggregator_v2':
            stacks_list = {'npm': [], 'maven': []}
            for data in stack_data:
                stack_info_template = {
                    'ecosystem': '',
                    'stack': [],
                    'unknown_dependencies': [],
                    'license': {
                        'conflict': False,
                        'unknown': []
                    },
                    'security': {
                        'cve_list': [],
                    },
                    'response_time': ''
                }
                try:
                    user_stack_info = data[0]['stack_data'][0]['user_stack_info']
                    if len(user_stack_info['dependencies']) == 0:
                        continue

                    stack_info_template['ecosystem'] = user_stack_info['ecosystem']
                    total_stack_requests['all'] += 1
                    total_stack_requests[stack_info_template['ecosystem']] += 1

                    stack_info_template['stack'] = self.normalize_deps_list(
                        user_stack_info['dependencies'])
                    all_deps[user_stack_info['ecosystem']].append(stack_info_template['stack'])
                    stack_str = ','.join(stack_info_template['stack'])
                    stacks_list[user_stack_info['ecosystem']].append(stack_str)

                    unknown_dependencies = []
                    for dep in user_stack_info['unknown_dependencies']:
                        dep['package'] = dep.pop('name')
                        unknown_dependencies.append(dep)
                    stack_info_template['unknown_dependencies'] = self.normalize_deps_list(
                        unknown_dependencies)
                    all_unknown_deps[user_stack_info['ecosystem']].\
                        append(stack_info_template['unknown_dependencies'])

                    stack_info_template['license']['unknown'] = \
                        user_stack_info['license_analysis']['unknown_licenses']['really_unknown']
                    all_unknown_lic.append(stack_info_template['license']['unknown'])

                    for pkg in user_stack_info['analyzed_dependencies']:
                        for cve in pkg['security']:
                            stack_info_template['security']['cve_list'].append(cve)
                            all_cve_list.append('{cve}:{cvss}'.
                                                format(cve=cve['CVE'], cvss=cve['CVSS']))

                    end_date, start_date = \
                        data[0]['_audit']['ended_at'], data[0]['_audit']['started_at']

                    response_time = self.datediff_in_millisecs(start_date, end_date)
                    stack_info_template['response_time'] = '%f ms' % response_time
                    total_response_time['all'] += response_time
                    total_response_time[stack_info_template['ecosystem']] += response_time
                    template['stacks_details'].append(stack_info_template)
                except (IndexError, KeyError, TypeError) as e:
                    logger.exception('Error: %r' % e)
                    continue

            unique_stacks_with_recurrence_count = {
                'npm': self.populate_key_count(stacks_list['npm']),
                'maven': self.populate_key_count(stacks_list['maven'])
            }
            unique_stacks_with_deps_count =\
                self.set_unique_stack_deps_count(unique_stacks_with_recurrence_count)

            # generate aggregated data section
            template['stacks_summary'] = {
                'total_stack_requests_count': total_stack_requests['all'],
                'npm': {
                    'stack_requests_count': total_stack_requests['npm'],
                    'unique_dependencies_with_frequency':
                    self.populate_key_count(self.flatten_list(all_deps['npm'])),
                    'unique_unknown_dependencies_with_frequency':
                    self.populate_key_count(self.flatten_list(all_unknown_deps['npm'])),
                    'unique_stacks_with_frequency': unique_stacks_with_recurrence_count['npm'],
                    'unique_stacks_with_deps_count': unique_stacks_with_deps_count['npm'],
                    'average_response_time': '{} ms'.format(
                        total_response_time['npm'] / total_stack_requests['npm'])
                },
                'maven': {
                    'stack_requests_count': total_stack_requests['maven'],
                    'total_stack_requests_count': total_stack_requests['maven'],
                    'unique_dependencies_with_frequency':
                        self.populate_key_count(self.flatten_list(all_deps['maven'])),
                    'unique_unknown_dependencies_with_frequency':
                        self.populate_key_count(self.flatten_list(all_unknown_deps['maven'])),
                    'unique_stacks_with_frequency': unique_stacks_with_recurrence_count['maven'],
                    'unique_stacks_with_deps_count': unique_stacks_with_deps_count['maven'],
                    'average_response_time': '{} ms'.format(
                        total_response_time['maven'] / total_stack_requests['maven'])
                },
                'unique_unknown_licenses_with_frequency':
                    self.populate_key_count(self.flatten_list(all_unknown_lic)),
                'unique_cves':
                    self.populate_key_count(all_cve_list),
                'total_average_response_time':
                    '{} ms'.format(total_response_time['all'] / len(template['stacks_details'])),
            }
            try:
                current_datetime = datetime.datetime.now()
                self.s3.store_json_content(template, current_datetime, frequency)
            except Exception as e:
                logger.exception('Unable to store the report on S3. Reason: %r' % e)
            return template
        else:
            # todo: user feedback aggregation based on the recommendation task results
            return None

    def retrieve_worker_results(self, start_date, end_date, id_list=[], worker_list=[],
                                frequency='weekly'):
        """Retrieve results for selected worker from RDB."""
        result = {}
        # convert the elements of the id_list to sql.Literal
        # so that the SQL query statement contains the IDs within quotes
        id_list = list(map(sql.Literal, id_list))
        ids = sql.SQL(', ').join(id_list).as_string(self.conn)

        for worker in worker_list:
            query = sql.SQL('SELECT {} FROM {} WHERE {} IN (%s) AND {} = \'%s\'').format(
                sql.Identifier('task_result'), sql.Identifier('worker_results'),
                sql.Identifier('external_request_id'), sql.Identifier('worker')
            )

            self.cursor.execute(query.as_string(self.conn) % (ids, worker))
            data = json.dumps(self.cursor.fetchall())

            # associate the retrieved data to the worker name
            result[worker] = self.normalize_worker_data(start_date, end_date, data, worker,
                                                        frequency)
        return result

    def get_report(self, start_date, end_date, frequency='weekly'):
        """Generate the stacks report."""
        ids = self.retrieve_stack_analyses_ids(start_date, end_date)
        if len(ids) > 0:
            worker_result = self.retrieve_worker_results(
                start_date, end_date, ids, ['stack_aggregator_v2'], frequency)
            return worker_result
        else:
            logger.error('No stack analyses found from {s} to {e} to generate an aggregated report'
                         .format(s=start_date, e=end_date))
            return False
