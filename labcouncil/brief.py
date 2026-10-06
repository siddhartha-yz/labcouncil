"""Versioned research inputs and daily task-start boundaries."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PERMISSIONS = ('model_calls', 'local_compute', 'public_research')


def normalize(value, idea, mode):
    defaults = {'idea': idea, 'resources': '', 'requirements': '',
        'permissions': {'model_calls': mode == 'real_case', 'local_compute': True, 'public_research': False},
        'work_time': {'all_day': True, 'start': '09:00', 'end': '18:00', 'timezone': 'Asia/Shanghai'}}
    if value is None:
        return defaults
    if not isinstance(value, dict) or set(value) - set(defaults):
        raise ValueError('本轮输入字段无效')
    result = {**defaults, **value}
    for key in ('idea', 'resources', 'requirements'):
        if not isinstance(result[key], str) or len(result[key]) > 4000:
            raise ValueError('本轮输入文字须不超过4000字')
        result[key] = result[key].strip()
    if not result['idea']:
        raise ValueError('请填写本轮 idea')
    permissions = result['permissions']
    if not isinstance(permissions, dict) or set(permissions) != set(PERMISSIONS) or any(type(v) is not bool for v in permissions.values()):
        raise ValueError('权限必须为明确的勾选项')
    hours = result['work_time']
    if not isinstance(hours, dict) or set(hours) != {'all_day', 'start', 'end', 'timezone'} or type(hours['all_day']) is not bool:
        raise ValueError('每日工作时段无效')
    for key in ('start', 'end'):
        raw = hours[key]
        if not isinstance(raw, str) or len(raw) != 5 or raw[2] != ':' or not raw[:2].isdigit() or not raw[3:].isdigit():
            raise ValueError('工作时间须为HH:MM')
        hour, minute = map(int, raw.split(':'))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError('工作时间须为有效的HH:MM')
    if not hours['all_day'] and hours['start'] == hours['end']:
        raise ValueError('开始和结束相同时，请明确选择全天可工作')
    try:
        ZoneInfo(hours['timezone'])
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError('请输入有效时区，例如Asia/Shanghai') from None
    return result


def in_work_time(brief, now):
    hours = brief['work_time']
    if hours['all_day']:
        return True
    local = datetime.fromtimestamp(now, timezone.utc).astimezone(ZoneInfo(hours['timezone']))
    current = local.hour * 60 + local.minute
    start, end = (int(hours[key][:2])*60+int(hours[key][3:]) for key in ('start', 'end'))
    return start <= current < end if start < end else current >= start or current < end


def start_blocker(brief, mode, now):
    if not brief['permissions']['local_compute']:
        return '未授权本地计算；当前执行器需要此权限，等待组会调整'
    if mode == 'real_case' and not brief['permissions']['model_calls']:
        return '未授权模型调用，等待组会调整'
    if not in_work_time(brief, now):
        return '等待下一次每日工作时段'
    return None


def make_plan(brief, mode):
    # This is a transparent bounded executor plan, not model-generated research.
    hours = brief['work_time']
    window = '每天全天' if hours['all_day'] else f"每天{hours['start']}–{hours['end']}（{hours['timezone']}）"
    return {'source': 'platform bounded plan', 'objective': brief['idea'],
        'granularity': '一次只启动一个可核验的短任务；按依赖顺序准备输入、计算、复算',
        'work_window': window, 'resources': brief['resources'], 'requirements': brief['requirements'],
        'steps': ['准备本轮输入与数据', '执行计算，保存实验数据和指标', '独立复算，整理报告，等待组会'],
        'unavailable': ['论文和仓库自动探索', '任意实验代码生成', '根据剩余资源自主规划并持续研究'],
        'executor': '真实Flash与固定工具' if mode == 'real_case' else '固定程序流程演示'}
