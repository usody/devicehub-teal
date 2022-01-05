from flask_wtf import FlaskForm
from wtforms import StringField, HiddenField, DateField, TextAreaField, SelectField, validators
from flask import g

from ereuse_devicehub.db import db
from ereuse_devicehub.resources.device.models import Device
from ereuse_devicehub.resources.lot.models import Lot


class LotDeviceForm(FlaskForm):
    lot = StringField(u'Lot', [validators.UUID()])
    devices = StringField(u'Devices', [validators.length(min=1)])

    def validate(self, extra_validators=None):
        is_valid = super().validate(extra_validators)

        if not is_valid:
            return False

        self._lot = Lot.query.filter(Lot.id == self.lot.data).filter(
            Lot.owner_id == g.user.id).one()

        devices = set(self.devices.data.split(","))
        self._devices = set(Device.query.filter(Device.id.in_(devices)).filter(
            Device.owner_id == g.user.id).all())

        if not self._devices:
            return False

        return True

    def save(self):
        self._lot.devices.update(self._devices)
        db.session.add(self._lot)
        db.session.commit()

    def remove(self):
        self._lot.devices.difference_update(self._devices)
        db.session.add(self._lot)
        db.session.commit()


class LotForm(FlaskForm):
    name = StringField(u'Name', [validators.length(min=1)])

    def __init__(self, *args, **kwargs):
        self.id = kwargs.pop('id', None)
        self.instance = None
        if self.id:
            self.instance = Lot.query.filter(Lot.id == self.id).filter(
                Lot.owner_id == g.user.id).one()
        super().__init__(*args, **kwargs)
        if self.instance and not self.name.data:
            self.name.data = self.instance.name

    def save(self):
        name = self.name.data.strip()
        if self.instance:
            if self.instance.name == name:
                return self.instance
            self.instance.name = name
        else:
            self.instance = Lot(name=name)

        if not self.id:
            db.session.add(self.instance)
            db.session.commit()
            return self.instance

        db.session.commit()
        return self.id

    def remove(self):
        if self.instance and not self.instance.devices:
            self.instance.delete()
            db.session.commit()
        return self.instance


class NewActionForm(FlaskForm):
    name = StringField(u'Name', [validators.length(max=50)])
    devices = HiddenField()
    date = DateField(u'Date')
    severity = SelectField(u'Severity', choices=[('Info', 'Ok'),
                                                 ('Notice', 'Notice'),
                                                 ('Warning', 'Warning'),
                                                 ('Error', 'Error')])
    description = TextAreaField(u'Description')
    lot = HiddenField()
    type = HiddenField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = None
        if self.lot.data:
            self.lot.data = self.lot.data.id

    def save(self):
        pass
