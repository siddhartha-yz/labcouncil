"""Small, transparent local language helpers. No model or execution authorization.

Only direct human statements become candidate settings; quoted, hypothetical and
question forms do not grant permissions. Unrecognized intent is left to dialogue.
"""
import re


def statement(message):
    return not re.search(r'[“”"<>]|```|(?:资料|教程|原文).*(?:写|说|提到)|例如|假如|如果|要是|(?:他说|她说)|[?？]|是否|是不是|会不会|能不能|可不可以|行不行|够不够',message)


def control_intent(message):
    if not statement(message):return None
    raw=message.strip().rstrip('。！! ')
    if re.search(r'(?:不要|别|不必)(?:暂停|取消|撤回)',raw):return None
    if re.search(r'(?:先|暂时)?(?:别|不要|不再).{0,3}(?:花钱|扣钱|收费)|(?:停止|停用).{0,3}(?:付费|模型调用)|(?:不要|别).{0,3}(?:扣费|消耗额度)',raw):return 'stop_spending'
    if re.search(r'(?:算了|取消安排|撤回|我改主意了|(?:刚才|刚刚|那个|这个).{0,6}(?:别做|不要做|不做了))',raw):return 'cancel'
    if re.search(r'暂停|停一下|停一停|先停|停止工作|先不要工作|别忙|先别干|不要继续|别一直跑|(?:等我|我回来).*(?:再|继续)|等我回来',raw):return 'pause'
    if raw in {'恢复工作','继续工作','恢复','继续','继续吧'}:return 'resume'
    return None


def natural_permissions(message):
    if not statement(message):return {}
    result={}
    for part in re.split(r'[，。；,;\n]',message):
        if re.search(r'(?:可以|允许|同意).*(?:上网|联网|找公开|搜公开|查公开)',part):result['public_research']=True
        if re.search(r'(?:别|不要|不许|禁止|不再|不能).*(?:上网|联网|查公开|找公开)',part):
            result.update(public_research=False,retry_public_reads=False)
        if re.search(r'(?:可以|允许|同意).*(?:用模型|调用模型|模型调用)',part):result['model_calls']=True
        if re.search(r'(?:禁止|不要|别|停用).*(?:用模型|调用模型|模型调用)',part):result['model_calls']=False
    return result


def resources(message):
    if not statement(message) or re.search(r'(?:其他限制|电脑).*(?:没变|不变)',message):return ''
    explicit=re.search(r'(?:^|[，。；,;\n])\s*(?:资源|可用资源)[：:]\s*([^\n]+)',message)
    if explicit:return explicit[1]
    parts=re.split(r'[，。；,;\n]',message)
    return '；'.join(p for p in parts if re.search(r'(?:我|我们).*(?:只有|只剩|手头|一台|电脑是)|(?:数据|设备|电脑|机器).*(?:只有|就|是|几百|几千|\d+行)|(?:我|我们).*(?:有|使用).*(?:笔记本|显卡|数据)',p))


def preferences(message):
    # A polite question about report style may be saved as a candidate preference;
    # it never grants permission or starts work. Quoted/hypothetical text is excluded.
    return not re.search(r'[“”"<>]|```|假如|如果|要是|(?:教程|资料|原文).*(?:写|说)',message) and bool(re.search(r'额外要求[：:]|写.{0,6}(?:简单|通俗|明白|像跟外行)|报告.*(?:外行|普通|大白话)|(?:缩写|英文).*解释|(?:失败|不好|负面).*留|显卡.*(?:别|不要)|(?:别|不要).*(?:安装|私有|电脑.*文件|训练)',message))


def local_reply(p,message):
    """Explain actual state before asking for a single actionable next step."""
    b=p['current_inputs']['body'];pending=p.get('group_proposal')
    no_model=not b['permissions']['model_calls'];demo=p['execution']['mode']=='simulation'
    suffix='要进一步讨论，可以点“选择可用工具”，只勾选模型讨论；安排仍会先让你确认。' if no_model and not demo else ''
    if re.search(r'教程|这两句.*意思',message):
        return '“模型讨论”让研究助手使用你配置的模型，会消耗对应账号用量；“公开资料查询”允许读取公开论文摘要和仓库资料，不代表允许读你的私人文件。引用教程不会开启权限。可以在“选择可用工具”逐项勾选，先看安排再决定。'
    if re.search(r'不敢点|不点能|工具.*(?:什么意思|怎么选)',message):
        return '没有选择必需工具时，研究不会开始；想法和已有资料仍会保留。不想使用模型，可以点“另开程序演示群”看固定小实验。想讨论时只勾选模型，想找公开资料再勾查询；提交后还有一张安排卡让你检查。'
    if pending and re.search(r'多久|时间|说到哪|还在|刚才|到哪一步',message):
        return f'还在。刚才的安排仍等你确认，还没有执行：{pending["brief"]["idea"]}\n最多投入{pending["brief"]["work_time"]["duration_minutes"]}分钟。你可以点“同意这个安排”，或点“我想改一下”补充；旧草稿和资料都保留。'
    if re.search(r'扣钱|免费|收费|花钱|扣费',message) and no_model:
        return '这条消息没有调用模型，当前也不会启动新的模型请求。可以先保留想法、查看已有资料，或点“另开程序演示群”体验固定小实验。演示不调用模型；真实模型会消耗对应账号用量，平台不能保证免费。'
    if re.search(r'训练.*(?:大模型|厉害)|装软件|安装软件',b['idea']+' '+message) and no_model:
        return '当前不能自动安装软件、训练大模型或运行任意GPU代码，所以还没有开始这些工作。可以先用一个小实验核对思路。你最想让它解决哪一个具体问题？'
    if re.search(r'名气|权威|直接信|机构',message) and no_model:
        return '机构或作者的名气不能替代结果核验。现在还没拿到这篇论文，也没运行其代码。能发论文标题或链接吗？我们再明确要核对哪个结果。'
    if re.search(r'复现',b['idea']) and no_model:
        return '目前没有定位到你说的那篇论文，也没有复现结果。能发论文链接、标题或记得的关键词吗？先找到具体材料，再说明可核对的实验与缺口。'
    if re.search(r'报告|结论|成果',message) and not p['artifacts'] and not p['tool_operations']:
        return '目前还没有报告或实验结果，不能先编一份结论。'+('研究工作还没开始。'+suffix if no_model and not demo else '可以先确认工作安排；有结果后会发在群里，也能从右上角“成果”查看。')
    if re.search(r'计划.*(?:全部|完整)|不知道.*(?:开始|怎么)|从哪|没想好',b['idea']+' '+message) and no_model:
        return '不用先把完整计划想好，可以边聊边缩小问题。你最想弄清哪个现象，或解决哪个具体问题？想法会留在这个群里；目前还没有启动研究。'
    if p['round_time']['expired']:
        return '本次投入时间已经到了，没有启动后续研究。已有报告和聊天仍保留。要继续做，需要明确新的投入时长；可以点工具选择改时长，再确认安排。任务和请求总额度不会因此增加。'
    if re.search(r'动静|开始|在找|进展|到哪|忙啥|现在|完成',message):
        done=sum(t['status']=='completed' for t in p['tasks'] if t['version']==p['version'])
        if no_model and not demo:return '还没有开始研究：目前未允许调用模型。'+suffix+'如果还没决定，可以继续补充想法。'
        return f'{"这是固定程序演示。" if demo else ""}当前安排完成{done}个步骤，已保存{len(p["artifacts"])}份报告。'+('后台已暂停，不启动新步骤。' if p['paused'] else '可以从右上角“进展”看等待、进行中或失败的原因。')
    if no_model:
        return '想法和这条消息已保留，目前还没有启动研究。'+suffix+'你也可以继续补充资源、限制，或者说还没想清楚的地方。'
    return None
