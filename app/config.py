from dataclasses import dataclass, field
from copy import deepcopy
import os
from pathlib import Path
from urllib.parse import urlparse
import json
from app.secrets import protect, unprotect

PROVIDERS = {
    'local': {'label': 'LM Studio', 'llm_base_url': 'http://127.0.0.1:1234/v1', 'llm_model': '', 'api_key': ''},
    'deepseek': {'label': 'DeepSeek 官方 API', 'llm_base_url': 'https://api.deepseek.com', 'llm_model': '', 'api_key': ''},
    'openai': {'label': 'OpenAI 官方 API', 'llm_base_url': 'https://api.openai.com/v1', 'llm_model': '', 'api_key': ''},
}


@dataclass(slots=True)
class Settings:
    llm_base_url: str = os.getenv('CAMPUSFLOW_LLM_BASE_URL', 'http://127.0.0.1:1234/v1')
    llm_model: str = os.getenv('CAMPUSFLOW_LLM_MODEL', '')
    llm_timeout_seconds: float = float(os.getenv('CAMPUSFLOW_LLM_TIMEOUT', '180'))
    timezone: str = os.getenv('CAMPUSFLOW_TIMEZONE', 'Asia/Shanghai')
    data_dir: Path = Path(os.getenv('CAMPUSFLOW_DATA_DIR', 'data'))
    provider: str = 'local'
    api_key: str = field(default='', repr=False)
    profiles: dict = field(default_factory=dict, repr=False)

    def validate(self):
        if self.provider not in PROVIDERS:
            raise ValueError('不支持的模型来源')
        if self.provider != 'local':
            self.llm_base_url = PROVIDERS[self.provider]['llm_base_url']
            return
        parsed = urlparse(self.llm_base_url)
        if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1'} or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('第一版模型地址须为本机 http://127.0.0.1:端口/v1 或 localhost 地址')
        self.llm_base_url = self.llm_base_url.rstrip('/')
        if parsed.path in {'', '/'}:
            self.llm_base_url += '/v1'
        elif parsed.path.rstrip('/') != '/v1':
            raise ValueError('LM Studio 地址请填写服务器地址或以 /v1 结尾的地址')

    def load(self, path):
        self.profiles = deepcopy(PROVIDERS)
        self.profiles['local'].update(llm_base_url=self.llm_base_url, llm_model=self.llm_model)
        for provider, env in [('openai','OPENAI_API_KEY'),('deepseek','DEEPSEEK_API_KEY')]:
            self.profiles[provider]['api_key'] = os.getenv(env, '')
        if Path(path).exists():
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            if 'profiles' in data:
                for provider, saved in data['profiles'].items():
                    if provider not in self.profiles: continue
                    self.profiles[provider].update(llm_model=saved.get('llm_model',''))
                    if provider == 'local': self.profiles[provider]['llm_base_url'] = saved.get('llm_base_url', PROVIDERS['local']['llm_base_url'])
                    if saved.get('encrypted_key'): self.profiles[provider]['api_key'] = unprotect(saved['encrypted_key'])
                self.provider = data.get('provider', 'local')
            else:
                self.profiles['local'].update(llm_base_url=data.get('llm_base_url',self.llm_base_url), llm_model=data.get('llm_model',self.llm_model))
        self.activate(self.provider)

    def activate(self, provider):
        if provider not in self.profiles: raise ValueError('不支持的模型来源')
        self.provider = provider
        profile = self.profiles[provider]
        self.llm_base_url, self.llm_model, self.api_key = profile['llm_base_url'], profile['llm_model'], profile.get('api_key','')
        self.validate()

    def save(self, path):
        self.validate()
        data = {'provider': self.provider, 'profiles': {}}
        for provider, profile in self.profiles.items():
            data['profiles'][provider] = {'llm_base_url': profile['llm_base_url'], 'llm_model': profile['llm_model'], 'encrypted_key': protect(profile.get('api_key',''))}
        target = Path(path)
        tmp = target.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(target)

    def public(self):
        return {'provider': self.provider, 'llm_base_url': self.llm_base_url, 'llm_model': self.llm_model,
                'profiles': {provider: {k:v for k,v in profile.items() if k != 'api_key'} | {'has_api_key':bool(profile.get('api_key'))} for provider,profile in self.profiles.items()}}

