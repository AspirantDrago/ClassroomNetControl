import re
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, SecretStr, model_validator

ActionName = Literal['install-updates-and-power-down', 'power-down-confirmed', 'power-down-delayed',
                     'login', 'logout', 'screen-off', 'screen-on', 'message', 'website', 'command']
ADMIN_ACTIONS = {'install-updates-and-power-down', 'command'}
FEATURE_IDS = {
    'install-updates-and-power-down': '09bcb3a1-fc11-4d03-8cf1-efd26be8655b',
    'power-down-confirmed': 'ea2406be-d5c7-42b8-9f04-53469d3cc34c',
    'power-down-delayed': '352de795-7fc4-4850-bc57-525bcb7033f5',
    'login': '7310707d-3918-460d-a949-65bd152cb958',
    'logout': '7311d43d-ab53-439e-a03a-8cb25f7ed526',
    'screen-off': 'ccb535a2-1d24-4cc1-a709-8b47d2b2ac79',
    'screen-on': 'ccb535a2-1d24-4cc1-a709-8b47d2b2ac79',
    'message': 'e75ae9c8-ac17-4d00-8f0d-019348346208',
    'website': '8a11a75d-b3db-48b6-b9cb-f8422ddd5b0c',
    'command': 'da9ca56a-b2ad-4fff-8f8a-929b2927b442',
}

class DeviceAction(BaseModel):
    action: ActionName
    text: str = Field(default='', max_length=16000, repr=False)
    username: str = Field(default='', max_length=256)
    password: SecretStr | None = Field(default=None, repr=False)
    seconds: int = Field(default=0, ge=0, le=604800, strict=True)
    confirmed: bool = False

    @model_validator(mode='after')
    def validate_action(self):
        if self.action in {'message', 'website', 'command'} and not self.text.strip():
            raise ValueError('Введите текст')
        if self.action == 'website':
            value = self.text.strip()
            if value.startswith('//'):
                value = 'http:' + value
            elif not re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', value) or re.match(r'^[^:/?#\s]+:\d+(?:[/?#]|$)', value):
                value = 'http://' + value
            url = urlsplit(value)
            if url.scheme.lower() not in {'http', 'https'} or not url.hostname or url.username or url.password:
                raise ValueError('Введите адрес сайта http:// или https://')
            # Validate numeric port range as well as host:port shorthand.
            _ = url.port
            self.text = value
        if self.action == 'login' and (not self.username.strip() or self.password is None or not self.password.get_secret_value()):
            raise ValueError('Введите логин и пароль')
        if self.action == 'power-down-delayed' and self.seconds < 1:
            raise ValueError('Задайте время от 1 секунды до 7 дней')
        if self.action == 'logout' and not self.confirmed:
            raise ValueError('Подтвердите выход пользователя')
        return self

    def wire(self):
        result = self.model_dump(exclude={'password'})
        if self.action == 'login' and self.password:
            result['password'] = self.password.get_secret_value()
        return result

    def feature_arguments(self):
        if self.action == 'login':
            return {'username': self.username.strip(), 'password': self.password.get_secret_value()}
        if self.action == 'power-down-delayed': return {'shutdownTimeout': self.seconds}
        if self.action == 'message': return {'text': self.text}
        if self.action == 'website': return {'websiteUrls': [self.text.strip()]}
        if self.action == 'command':
            import base64
            encoded = base64.b64encode(self.text.encode('utf-16-le')).decode('ascii')
            return {'applications': ['powershell.exe -NoProfile -NonInteractive -EncodedCommand ' + encoded]}
        return {}
