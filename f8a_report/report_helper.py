"""Various utility functions used across the repo."""

import os
import json
import logging
import datetime
import psycopg2
import psycopg2.extras
import itertools
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


pg = Postgres()
conn = pg.conn
cursor = pg.cursor


class ReportHelper:
    """Stack Analyses report helper functions."""

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

        cursor.execute(query.as_string(conn) % (start_date, end_date))
        rows = cursor.fetchall()

        id_list = []
        for row in rows:
            for col in row:
                id_list.append(col)

        return id_list

    def retrieve_worker_results(self, start_date, end_date, id_list=[], worker_list=[]):
        """Retrieve results for selected worker from RDB."""
        result = {}
        # convert the elements of the id_list to sql.Literal
        # so that the SQL query statement contains the IDs within quotes
        id_list = list(map(sql.Literal, id_list))
        ids = sql.SQL(', ').join(id_list).as_string(conn)

        for worker in worker_list:
            query = sql.SQL('SELECT {} FROM {} WHERE {} IN (%s) AND {} = \'%s\'').format(
                sql.Identifier('task_result'), sql.Identifier('worker_results'),
                sql.Identifier('external_request_id'), sql.Identifier('worker')
            )

            cursor.execute(query.as_string(conn) % (ids, worker))
            data = json.dumps(cursor.fetchall())

            # associate the retrieved data to the worker name
            result[worker] = self.normalize_worker_data(start_date, end_date, data, worker)
        return result

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
            print('Error: %r' % e)
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

    def normalize_worker_data(self, start_date, end_date, stack_data, worker):
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
                    print('Error: %r' % e)
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
            return template
        else:
            return None

    def get_report(self, start_date, end_date):
        """Generate the stacks report."""
        ids = self.retrieve_stack_analyses_ids(start_date, end_date)
        worker_result = self.retrieve_worker_results(
            start_date, end_date, ids, ['stack_aggregator_v2'])
        return worker_result
