"""Versioned research inputs and per-round elapsed-time budgets."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PERMISSIONS = ('model_calls', 'local_compute', 'public_research', 'retry_public_reads')
DEFAULT_DURATION_MINUTES = 120


def duration_minutes(brief):
    hours = brief.get('work_time', {})
    if 'duration_minutes' not in hours:
        return DEFAULT_DURATION_MINUTES
    value = hours['duration_minutes']
    if type(value) is not int or not 1 <= value <= 10080:
        raise ValueError('本轮工作时长须为1–10080分钟的整数')
    return value


def normalize(value, idea, mode):
    defaults = {'idea': idea, 'resources': '', 'requirements': '',
        'permissions': {'model_calls': mode != 'simulation', 'local_compute': True, 'public_research': False, 'retry_public_reads': False},
        'work_time': {'duration_minutes': DEFAULT_DURATION_MINUTES}}
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
    if isinstance(permissions,dict) and set(permissions) == set(PERMISSIONS)-{'retry_public_reads'}:
        permissions = {**permissions,'retry_public_reads':False}
        result['permissions'] = permissions
    if not isinstance(permissions, dict) or set(permissions) != set(PERMISSIONS) or any(type(v) is not bool for v in permissions.values()):
        raise ValueError('权限必须为明确的勾选项')
    hours = result['work_time']
    if not isinstance(hours, dict):
        raise ValueError('本轮工作时长无效')
    if set(hours) == {'all_day','start','end','timezone'}:
        # Accept old clients, but do not reinterpret a daily window as work done.
        if type(hours['all_day']) is not bool:
            raise ValueError('旧版每日工作时段无效')
        for key in ('start','end'):
            raw = hours[key]
            if not isinstance(raw,str) or len(raw)!=5 or raw[2]!=':' or not raw[:2].isdigit() or not raw[3:].isdigit():
                raise ValueError('旧版工作时间须为HH:MM')
            hour,minute = map(int,raw.split(':'))
            if not (0<=hour<24 and 0<=minute<60):raise ValueError('旧版工作时间无效')
        if not hours['all_day'] and hours['start']==hours['end']:raise ValueError('旧版开始和结束时间相同')
        try:ZoneInfo(hours['timezone'])
        except (ZoneInfoNotFoundError,ValueError,TypeError):raise ValueError('旧版时区无效') from None
    elif set(hours) != {'duration_minutes'}:
        raise ValueError('本轮工作时长字段无效')
    result['work_time'] = {'duration_minutes':duration_minutes(result)}
    return result


def round_time(inputs, now):
    minutes = duration_minutes(inputs['body'])
    started = inputs.get('budget_started_at',inputs['created'])
    deadline = started + minutes*60
    return {'duration_minutes':minutes,'started_at':started,'deadline_at':deadline,
        'remaining_seconds':max(0,deadline-now),'expired':now>=deadline,
        'legacy_default':'duration_minutes' not in inputs['body'].get('work_time',{}),
        'definition':'elapsed since round confirmation; includes pauses and service downtime'}


def start_blocker(brief, mode, now, started_at=None):
    if mode != 'research' and not brief['permissions']['local_compute']:
        return '未授权本地计算；当前执行器需要此权限，等待组会调整'
    if mode != 'simulation' and not brief['permissions']['model_calls']:
        return '未授权模型调用，等待组会调整'
    if started_at is not None and now>=started_at+duration_minutes(brief)*60:
        return '投入时间已到；需要新预算时直接在群里说明'
    return None


def make_plan(brief, mode, backend='deepseek'):
    executor = 'Codex CLI · gpt-6.1-sol · high' if backend == 'codex_cli' else '真实Flash'
    duration = duration_minutes(brief)
    window = f'本轮最多{duration}分钟；截止以项目保存的投入窗口为准，到时不再启动新步骤，已启动步骤可保存结果'
    if mode == 'research':
        return {'source':'platform research boundaries; actual agent plan in each artifact','objective':brief['idea'],
            'granularity':'每步选择一个可核验的查询或计算，依据剩余时间和资源安排；最多六步后向你汇报',
            'work_window':window,'resources':brief['resources'],'requirements':brief['requirements'],
            'steps':['agent根据输入规划下一步','保存公开资料或受控计算证据','依据已有证据继续，达到时间或资源边界后等组会'],
            'unavailable':['任意仓库代码执行','完整论文全文阅读和论文实验复现','任意GPU训练'],
            'executor':executor+'与有界研究工具'}
    return {'source':'platform bounded plan','objective':brief['idea'],
        'granularity':'一次只启动一个可核验的短任务；按依赖顺序准备输入、计算、复算',
        'work_window':window,'resources':brief['resources'],'requirements':brief['requirements'],
        'steps':['准备本轮输入与数据','执行计算，保存实验数据和指标','独立复算，整理报告，等待组会'],
        'unavailable':['论文和仓库自动探索','任意实验代码生成','根据剩余资源自主规划并持续研究'],
        'executor':executor+'与固定工具' if mode!='simulation' else '固定程序流程演示'}
