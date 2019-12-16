import itertools
import json
from pathlib import Path
from typing import Set

import click
import click_spinner
import ereuse_utils.cli
import yaml
from ereuse_utils.test import ANY

from ereuse_devicehub.client import UserClient
from ereuse_devicehub.db import db
from ereuse_devicehub.resources.action import models as m
from ereuse_devicehub.resources.agent.models import Person
from ereuse_devicehub.resources.device.models import Device
from ereuse_devicehub.resources.lot.models import Lot
from ereuse_devicehub.resources.tag.model import Tag
from ereuse_devicehub.resources.user import User


class Dummy:
    TAGS = (
        'tag1',
        'tag2',
        'tag3'
    )
    """Tags to create."""
    ET = (
        ('DT-AAAAA', 'A0000000000001'),
        ('DT-BBBBB', 'A0000000000002'),
        ('DT-CCCCC', 'A0000000000003'),
        ('DT-BRRAB', '04970DA2A15984'),
        ('DT-XXXXX', '04e4bc5af95980')
    )
    """eTags to create."""
    ORG = 'eReuse.org CAT', '-t', 'G-60437761', '-c', 'ES'
    """An organization to create."""

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.app.cli.command('dummy', short_help='Creates dummy devices and users.')(self.run)

    @click.option('--tag-url', '-tu',
                  type=ereuse_utils.cli.URL(scheme=True, host=True, path=False),
                  default='http://localhost:8081',
                  help='The base url (scheme and host) of the tag provider.')
    @click.option('--tag-token', '-tt',
                  type=click.UUID,
                  default='899c794e-1737-4cea-9232-fdc507ab7106',
                  help='The token provided by the tag provider. It is an UUID.')
    @click.confirmation_option(prompt='This command (re)creates the DB from scratch.'
                                      'Do you want to continue?')
    def run(self, tag_url, tag_token):
        runner = self.app.test_cli_runner()
        self.app.init_db('Dummy',
                         'ACME',
                         'acme-id',
                         tag_url,
                         tag_token,
                         erase=True,
                         common=True)
        print('Creating stuff...'.ljust(30), end='')
        with click_spinner.spinner():
            out = runner.invoke('org', 'add', *self.ORG).output
            org_id = json.loads(out)['id']
            user1 = self.user_client('user@dhub.com', '1234', 'user1', '0xC79F7fE80B5676fe38D8187b79d55F7A61e702b2')

            # todo put user's agent into Org
            for id in self.TAGS:
                user1.post({'id': id}, res=Tag)
            for id, sec in self.ET:
                runner.invoke('tag', 'add', id,
                              '-p', 'https://t.devicetag.io',
                              '-s', sec,
                              '-o', org_id)
            # create tag for pc-laudem
            runner.invoke('tag', 'add', 'tagA',
                          '-p', 'https://t.devicetag.io',
                          '-s', 'tagA-secondary')
        files = tuple(Path(__file__).parent.joinpath('files').iterdir())
        print('done.')
        sample_pc = None  # We treat this one as a special sample for demonstrations
        pcs = set()  # type: Set[int]
        with click.progressbar(files, label='Creating devices...'.ljust(28)) as bar:
            for path in bar:
                with path.open() as f:
                    snapshot = yaml.load(f)
                s, _ = user1.post(res=m.Snapshot, data=snapshot)
                if s.get('uuid', None) == 'ec23c11b-80b6-42cd-ac5c-73ba7acddbc4':
                    sample_pc = s['device']['id']
                else:
                    pcs.add(s['device']['id'])
                if s.get('uuid', None) == 'de4f495e-c58b-40e1-a33e-46ab5e84767e':  # oreo
                    # Make one hdd ErasePhysical
                    hdd = next(hdd for hdd in s['components'] if hdd['type'] == 'HardDrive')
                    user1.post({'type': 'ErasePhysical', 'method': 'Shred', 'device': hdd['id']},
                              res=m.Action)
        assert sample_pc
        print('PC sample is', sample_pc)
        # Link tags and eTags
        for tag, pc in zip((self.TAGS[1], self.TAGS[2], self.ET[0][0], self.ET[1][1]), pcs):
            user1.put({}, res=Tag, item='{}/device/{}'.format(tag, pc), status=204)

        # Perform generic actions
        for pc, model in zip(pcs,
                             {m.ToRepair, m.Repair, m.ToPrepare, m.Ready, m.ToPrepare,
                              m.Prepare}):
            user1.post({'type': model.t, 'devices': [pc]}, res=m.Action)

        # Perform a Sell to several devices
        user1.post(
            {
                'type': m.Sell.t,
                'to': user1.user['individuals'][0]['id'],
                'devices': list(itertools.islice(pcs, len(pcs) // 2))
            },
            res=m.Action)

        parent, _ = user1.post(({'name': 'Parent'}), res=Lot)
        child, _ = user1.post(({'name': 'Child'}), res=Lot)
        parent, _ = user1.post({},
                              res=Lot,
                              item='{}/children'.format(parent['id']),
                              query=[('id', child['id'])])

        lot, _ = user1.post({},
                           res=Lot,
                           item='{}/devices'.format(child['id']),
                           query=[('id', pc) for pc in itertools.islice(pcs, len(pcs) // 3)])
        assert len(lot['devices'])

        # Keep this at the bottom
        inventory, _ = user1.get(res=Device)
        assert len(inventory['items'])

        i, _ = user1.get(res=Device, query=[('search', 'intel')])
        assert 12 == len(i['items'])
        i, _ = user1.get(res=Device, query=[('search', 'pc')])
        assert 14 == len(i['items'])

        # Let's create a set of actions for the pc device
        # Make device Ready

        user1.post({'type': m.ToPrepare.t, 'devices': [sample_pc]}, res=m.Action)
        user1.post({'type': m.Prepare.t, 'devices': [sample_pc]}, res=m.Action)
        user1.post({'type': m.Ready.t, 'devices': [sample_pc]}, res=m.Action)
        user1.post({'type': m.Price.t, 'device': sample_pc, 'currency': 'EUR', 'price': 85},
                  res=m.Action)
        # todo test reserve
        user1.post(  # Sell device
            {
                'type': m.Sell.t,
                'to': user1.user['individuals'][0]['id'],
                'devices': [sample_pc]
            },
            res=m.Action)
        # todo Receive

        user1.get(res=Device, item=sample_pc)  # Test
        anonymous = self.app.test_client()
        html, _ = anonymous.get(res=Device, item=sample_pc, accept=ANY)
        assert 'intel core2 duo cpu' in html

        # For netbook: to preapre -> torepair -> to dispose -> disposed
        print('⭐ Done.')

    def user_client(self, email: str, password: str, name: str, ethereum_address: str):
        user1 = User(email=email, password=password, ethereum_address=ethereum_address)

        user2 = User(email='user2@test.com', password='1234', ethereum_address='0x56EbFdbAA98f52027A9776456e4fcD5d91090818')
        user3 = User(email='user3@test.com', password='1234', ethereum_address='0xF88618956696aB7e56Cb7bc87d9848E921C4FDaA')

        user1.individuals.add(Person(name=name))
        db.session.add(user1)
        db.session.add(user2)
        db.session.add(user3)

        db.session.commit()
        client = UserClient(self.app, user1.email, password,
                            response_wrapper=self.app.response_class)
        client.login()
        return client
