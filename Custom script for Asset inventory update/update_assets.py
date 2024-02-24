import sys
import json
from urllib2 import Request, urlopen, HTTPError
from urllib2 import ssl
from optparse import OptionParser, BadOptionError, AmbiguousOptionError

class RestApiClient:
    def __init__(self, args):
        self.headers = {'Accept': 'application/json'}
        self.headers['Version'] = '19.0'
        self.headers['Content-Type'] = 'application/json'
        self.auth = {'SEC': args[0].token}
        self.headers.update(self.auth)
        self.server_ip = args[0].ip
        self.base_uri = '/api/'
        self.quiet = not args[0].verbose

    def call_api(self, endpoint, method, headers=None, params=[], data=None, quiet=False):
        path = self.parse_path(endpoint, params)
        if not headers:
            headers = self.headers
        else:
            for key, value in self.headers.items():
                if not headers.get(key):
                    headers[key] = value

        if not self.quiet:
            print('\nSending ' + method + ' request to: ' + 'https://' + self.server_ip + self.base_uri + path + '\n')

        context = ssl._create_unverified_context()
        request = Request('https://' + self.server_ip + self.base_uri + path, headers=headers)
        request.get_method = lambda: method
        try:
            return urlopen(request, data, context=context)
        except HTTPError as e:
            return e

    def parse_path(self, endpoint, params):
        path = endpoint + '?'
        if isinstance(params, list):
            for kv in params:
                if kv[1]:
                    path += kv[0] + '=' + (kv[1].replace(' ', '%20')).replace(',', '%2C') + '&'
        else:
            for k, v in params.items():
                if v:
                    path += k + '=' + v.replace(' ', '%20').replace(',', '%2C') + '&'
        return path[:len(path) - 1]

class PassThroughOptionParser(OptionParser):
    def _process_args(self, largs, rargs, values):
        while rargs:
            try:
                OptionParser._process_args(self, largs, rargs, values)
            except (BadOptionError, AmbiguousOptionError) as e:
                largs.append(e.opt_str)

def get_parser():
    parser = PassThroughOptionParser(add_help_option=False)
    parser.add_option('-h', '--help', help='Show help message', action='store_true')
    parser.add_option('-i', '--ip', default="127.0.0.1", help='IP or Host of the QRadar console', action='store')
    parser.add_option('-t', '--token', help='QRadar authorized service token', action='store')
    parser.add_option('-f', '--file', help='File with assets to load.', action='store')
    parser.add_option('-d', '--fields', help='Display asset model fields', action='store_true')
    parser.add_option('-v', '--verbose', help='Verbose output', action='store_true')
    return parser

def main():
    parser = get_parser()
    args = parser.parse_args()

    if args[0].help or not (args[0].file or args[0].fields) or not args[0].ip or not args[0].token:
        print >> sys.stderr, "A simple utility to load a CSV file with asset information into the QRadar asset model based on IP address"
        print >> sys.stderr, parser.format_help().strip()
        exit(0)

    api_client = RestApiClient(args)

    print("Retrieving asset fields")
    response = api_client.call_api('asset_model/properties', 'GET', None, {}, None)
    response_content = response.read().decode('utf-8')
    print("Response Content: {}".format(response_content))
    response_json = json.loads(response_content)

    if response.code != 200:
        print("When retrieving assets : " + str(response.code))
        print(json.dumps(response_json, indent=2, separators=(',', ':')))
        exit(1)

    asset_field_lookup = {}
    if args[0].fields:
        print("Asset fields:")
    for asset_field in response_json:
        asset_field_lookup[asset_field['name']] = asset_field['id']
        if args[0].fields:
            print(asset_field['name'])

    if not args[0].file:
        exit(1)

    print("Retrieving assets from QRadar")
    response = api_client.call_api('asset_model/assets', 'GET', None, {}, None)
    response_content = response.read().decode('utf-8')

    if response.code != 200:
        print("Error retrieving assets: " + str(response.code))
        print(response_content)
        exit(1)

    response_json = json.loads(response_content)
    ip_assetid_lookup = {}
    for asset in response_json:
        for interface in asset.get('interfaces', []):
            for ip_address in interface.get('ip_addresses', []):
                ip_value = ip_address.get('value')
                if ip_value:
                    ip_assetid_lookup[ip_value] = asset['id']

    with open(args[0].file, 'r') as file:
        columnnames = file.readline().strip()
        fields = columnnames.split(',')

        for current_line, line in enumerate(file, start=2):
            data_fields = line.strip().split(',')

            json_string = "{ \"properties\": [ "
            ip_address = ''
            if len(data_fields) != len(fields):
                print("Error: Incorrect number of fields at line {}".format(current_line))
                continue

            for index, data_field in enumerate(data_fields):
                data_field = data_field.strip()
                if index == 0:
                    ip_address = data_field
                    if ip_assetid_lookup.get(ip_address, '') == '':
                        print("Error: IP address {} at line {} not found in QRadar Asset DB".format(ip_address, current_line))
                        break
                else:
                    json_string += "{ \"type_id\":" + str(asset_field_lookup.get(fields[index], '')) + \
                                   ",\"value\":\"" + data_field + "\"}"
                    if index < len(data_fields) - 1:
                        json_string += ","

            json_string += "]}"

            if ip_address in ip_assetid_lookup:
                response = api_client.call_api('asset_model/assets/' + str(ip_assetid_lookup[ip_address]), 'POST',
                                               {b'Accept': 'text/plain'}, {}, json_string)

                response_content = response.read().decode('utf-8')
                print("Response Content: {}".format(response_content))

                if response.code == 200 or response.code == 202:
                    print("Asset updated successfully")
                else:
                    print("Error updating asset: {} at line {}".format(ip_address, current_line))
                    print("Response Code: {}".format(response.code))
                    print("Response Content: {}".format(response_content))

if __name__ == "__main__":
    main()