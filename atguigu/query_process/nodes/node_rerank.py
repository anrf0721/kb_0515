"""
author: anrf
date:8/10/2026
desc:
"""

import asyncio
import json
import dashscope
from http import HTTPStatus

from atguigu.config.config import RerankConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import logger
from atguigu.tool.reranker_tool import text_rerank


class NodeRerank(NodeBase):
    """
    节点功能：使用 Cross-Encoder 模型对 RRF 后的结果进行精确打分重排。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_rerank"

    def process(self, state: QueryGraphState):
        """
        节点逻辑
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """

        # TODO

        logger.info(f"【{self.name}】节点逻辑")
        rrf_chunks = state.get('rrf_chunks')
        rewritten_query = state.get('rewritten_query')

        new_docs = [
            {
                'title' : doc.get('item_name',doc.get('file_title')) if doc.get('source') == 'local' else doc.get('title'),
                'content' : doc.get('entity_content'),
                'url' : doc.get('url'),
                'source' : doc.get('source')
            }
            for doc in rrf_chunks
        ]
        texts = [doc['content'] for doc in new_docs]
        # logger.info(new_docs)
        res = text_rerank(rewritten_query, texts,10)
        # logger.info(res)
        for doc in res:
            new_docs[doc['index']]['score'] = doc['score']
        # logger.info(new_docs)
        rerank_docs = [new_docs[doc['index']] for doc in res]
        # 这种写法必须要搭配len(new_docs)
        # rerank_docs = sorted(new_docs,key=lambda x: x['score'], reverse=True)
        # logger.info(rerank_docs)

        # 断崖检测
        RERANK_MAX_TOPK: int = 10
        # 最小 TopK：至少保留前 N 条（>=1，且 <= RERANK_MAX_TOPK）
        RERANK_MIN_TOPK: int = 3  # 总数最少条数
        # 断崖阈值（相对）
        RERANK_GAP_RATIO: float = 0.25
        # 断崖阈值（绝对）
        RERANK_GAP_ABS: float = 0.20

        use_max_topk = min(RERANK_MAX_TOPK, len(rrf_chunks))
        use_min_topk = min(RERANK_MIN_TOPK, len(rrf_chunks))
        final_rerank_chunks = []
        for i in range(use_min_topk -1, use_max_topk -1):
            current_score = rerank_docs[i]['score']
            next_score = rerank_docs[i+1]['score']
            abs_gap = current_score - next_score
            gap_ratio = abs_gap / (current_score + 1e-6)
            if abs_gap > RERANK_GAP_ABS or gap_ratio > RERANK_GAP_RATIO:
                final_rerank_chunks = rerank_docs[:i+1]
                break
            else:
                final_rerank_chunks = rerank_docs[:use_max_topk]

        return {
            # 注意：key 必须是 state 里定义的 reranked_docs，否则下游节点拿不到数据
            'reranked_docs' : final_rerank_chunks
        }

if __name__ == '__main__':
    init_state = {
        "rewritten_query": "关于hak180烫金机如何使用",
        'rrf_chunks' : [
        {
            "id": 468365666850726483,
            "entity_content": "brotherhak180烫金机-## 设备\n\n![设备使用注意事项：防触电、防火、防烫伤，远离儿童",
            "title": "## 设备",
            "item_name": "brotherhak180烫金机",
            "score": 0.03252247488101534,
            "source": "local"
        },
        {
            "id": 468365666850726494,
            "entity_content": "brotherhak180烫金机-## 设备\n\n![设备安全放置与使用指南](http://192.168.100.88:9000/my111/upload-images/c61a7f4e923881679f747508ae309c39dc221685344b068009256b1b3a40cc00",
            "title": "## 设备",
            "item_name": "brotherhak180烫金机",
            "score": 0.031746031746031744,
            "source": "local"
        },
        {
            "id": 468365666850726496,
            "entity_content": "brotherhak180烫金机-## 设备\n\n![安全使用设备，避免触电与受伤",
            "title": "## 设备",
            "item_name": "brotherhak180烫金机",
            "score": 0.03131881575727918,
            "source": "local"
        },
        {
            "id": 468365666850726501,
            "entity_content": "brotherhak180烫金机-## 为设备选择一个安全的位置\n\n![设备安全放置与电源使用注意事项](http://192.168.100.88:9000/my111/upload-images/cc5ee1ac24ebb2707d40dc7a234a8b243f55f5bf08fabc683859be6fdf096ffa",
            "title": "## 为设备选择一个安全的位置",
            "item_name": "brotherhak180烫金机",
            "score": 0.030834914611005692,
            "source": "local"
        },
        {
            "id": 468365666850726505,
            "entity_content": "brotherhak180烫金机-## 为设备选择一个安全的位置\n\n。](http://192.168.100.88:9000/my111/upload-images/8e839864036a7326885565163d99117ea943ecd29a656c85e7aa4052a9b9d28d",
            "title": "## 为设备选择一个安全的位置",
            "item_name": "brotherhak180烫金机",
            "score": 0.030776515151515152,
            "source": "local"
        },
        {
            "id": 468365666850726475,
            "entity_content": "brotherhak180烫金机-## HAK 180 烫金机\n\n产品安全手册（简体中文）\n\n感谢您购买 HAK 180 烫金机。\n\n在使用本设备之前，请先阅读本手册，包括所有预防措施。阅读本手册后，请妥善保管。\n\n有关使用本设备的更多信息，请参阅使用说明书，其可在兄弟 (中国)商业有限公司技术服务支持网站 http://www.95105369.com/Web/Manuals.aspx 上找到。建议您先通读使用说明书，再使用本设备。\n\n如需获得常见问题解答、故障排除和说明书，请访问\n\nhttp://www.95105369.com。\n\n对于本设备所有者不遵守本指南中规定的说明操作而导致的损害，Brother 不承担任何责任。",
            "title": "## HAK 180 烫金机",
            "item_name": "brotherhak180烫金机",
            "score": 0.030776515151515152,
            "source": "local"
        },
        {
            "id": 468365666850726493,
            "entity_content": "brotherhak180烫金机-## 设备\n\n•\t将本设备放置在平整、水平且稳定的表面上（如桌面），避免震动和冲击。\n\n•\t将本设备放置在通风良好的环境中。\n\n•\t为了防止人员受伤，请谨慎操作，避免将手指放置在图中所示的区域中。",
            "title": "## 设备",
            "item_name": "brotherhak180烫金机",
            "score": 0.030309988518943745,
            "source": "local"
        },
        {
            "entity_content": "兄弟(中国)发布烫金机,满足高端文印需求 在邀请函、贺卡或者是红包上轻松呈现出流光溢彩的烫金效果,随着兄弟(中国)23日正式推出的Brother HAK180烫金机而成为现实。这款体形轻巧烫印机的面市,改变了以往需要到工厂定制才能实现烫金文印品的历史。个人用户只需在纸张介质上使用激光打印机打印好内容,再放入兄弟烫金机HAK180中,即可实现一键烫印,省去繁杂的软件编辑、电脑连接过程。 近年来,文印市场逐渐呈现精细化发展趋势,拥有核心技术的兄弟烫金机HAK180则恰好是可以满足高端文印需求的一款产品。为了让更多用户体验这股“金色能量”,兄弟(中国)携全新烫金机Brother HAK180,以“引领鎏金岁月,创新成就JIN界”为发布会主题,于12月23日,带来了一场线上多平台直播,线下多地共享的双线联动发布会,向中国用户全方位展示烫金之美。 兄弟(中国)商业有限公司董事长兼总裁尹炳新先生在当天的发布会上介绍,相关数据显示,中国是全球烫金文印市场规模最大的国家,占据全球60%的份额,其次是德国和日本。基于中国庞大的市场潜力,为满足高端文印市场对于个性化烫金需求,解决繁杂制版工序及成本高企等诸多困扰,兄弟集团决定在中国市场推出 “便捷使用”和“精品烫印”于一身的烫金机。 尹炳新先生介绍,以往实现烫金效果需要把产品送往工厂,交由大型专业设备进行处理。而兄弟(中国)推出的HAK180烫金机体积小巧,无需制版,避免环境污染,操作简便。据了解,这款产品可瞬间实现烫金效果,可广泛适用于各类场景,如精美邀请函,高档菜单与座位卡,激励学子的金色奖状等各类需要高品质,个性化定制的场景,满足学校,商务公司,高档宴会酒店等多用户需求。 据介绍,HAK180烫金机广泛支持各类纸张,胜任各式复杂情况,可高效便捷地为用户完成繁重任务。另外,HAK180烫金机在无版烫金与读秒烫金的基础之上,采用“金”“银”“红”三色烫金薄膜设计,让烫金效果达到纤毫毕现的水准。无论是纤细线条,亦或微小字体,都能精准呈现。清晰的烫印效果,杜绝棱角、毛边、断线、模糊等恼人问题。同时烫印的内容耐得住长期保存,即便用手指刮抠也不会掉色或脱落,高品质烫金将为用户带来无可替代的体验。 整体上,做为凝聚着百年企业核心技术的Brother HAK180烫金机集合了兄弟集团始终坚持的高质量与高性价比的产品力,赋能其“无版烫印”、“多页连续烫金”、“纤毫毕现品质呈现”多重创新技术,以提升用户烫金体验,为高端文印与商务交流提供更优质、更创新的解决方案。 顺应市场的需求,兄弟(中国)面向中国市场",
            "title": "兄弟(中国)发布烫金机,满足高端文印需求",
            "url": "https://www.thepaper.cn/newsDetail_forward_15996505",
            "source": "web",
            "score": 0.029508196721311476
        },
        {
            "id": 468365666850726476,
            "entity_content": "brotherhak180烫金机-## HAK 180 烫金机\n\n•\t对于保养、调整或维修事宜，请联系 Brother 呼叫中心或您当地的Brother 经销商。\n\n•\t如果本设备工作不正常或发生任何错误，请关闭本设备，拔下所有电缆，然后联系 Brother 呼叫中心或您当地的 Brother 经销商。\n\n•\t本文档中提供的信息可能会随时更改，恕不另行通知。\n\n•\t严禁未经授权擅自复制或重制本文档的任何部分或全部内容。\n\n•\t请注意，对于使用通过本设备制作的产品造成的任何损坏或利润损失，或者故障、维修导致的数据消失或更改，或者第三方提出的任何索赔，我们不承担任何责任。",
            "title": "## HAK 180 烫金机",
            "item_name": "brotherhak180烫金机",
            "score": 0.02919863597612958,
            "source": "local"
        },
        {
            "entity_content": "HAK180 烫金机 零售价 面议 最大15PPM烫金速度  可选7PPM烫金速度  无版烫印  配备最大44页标准ADF进纸器  支持省膜模式  10字符x2行LCD液晶屏  HAK180烫金机,凭借其高速、高品质、以及出色的细节小字烫印效果,成为定制化专属机型。可烫印90g/m²~350g/m²的A4各类型纸张,支持各类广泛的应用领域。 高效、稳定的进纸结构 配备44页标准ADF进纸器,支持90g/m²~350g/m²的各类纸张(普通纸、薄纸、再生纸、厚纸等),进纸通道结构稳定可靠,支持连续烫印。 * 350g/m²支持12页自动进纸 * 最大支持44页进纸容量(90g/m²)烫印面朝下 高速连续烫金 HAK180针对不同厚度、介质的纸张提供两种可选烫金速度。15ppm满足普通规格纸张的高效烫金需求,7ppm适合稍厚纸张的烫金。 10字符×2行LCD液晶屏 10字符×2行LCD液晶屏,2个自定义按键,操作直观,方便快捷。 产品规格  一般参数  正常工作环境(温度): 10 ~ 32 摄氏度(50 ~ 90 华氏度) 正常工作环境(相对湿度): 20 % ~ 80 % 机器尺寸: W 384.2mm×D 330.2mm×H 356.2mm 重量(含包装箱): 16.9kg 电源: 220~240 V 消费电力(烫印中): 少于340W 消费电力(待机中): 少于7W 消费电力(关机): 少于0.04W LCD液晶屏尺寸: 48.0mm×10.9mm 节省烫金膜功能: 支持(在省膜模式中“跳过”和“中间”功能, 仅适用全幅烫金膜盒) 烫印参数  最大烫印速度 (A4): 最高达15 ppm 可选烫印速度(A4): 7 ppm 视频 烫金机-HAK180-烫印速度调整-7PPM 烫金机-HAK180-安装耗材 烫金机-HAK180-更换耗材 兄弟机床公众号 数码打印机公众号 创意标签P-touch Candy",
            "title": "HAK180",
            "url": "https://www.brother.cn/hak/hak180",
            "source": "web",
            "score": 0.02903225806451613
        }
    ],
    }
    node = NodeRerank()
    result = node(init_state)
    logger.info(json_format(result))
