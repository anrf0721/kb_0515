"""
author: anrf
date:8/10/2026
desc:
"""
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import logger


class NodeRrf(NodeBase):
    """
    节点功能：Reciprocal Rank Fusion
    将多路召回的结果（向量、HyDE、Web）进行加权融合排序。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_rrf"
    K = 60
    def process(self, state: QueryGraphState):
        """
        节点逻辑
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """
        # TODO
        logger.info(f"【{self.name}】节点逻辑")
        embedding_chunks = state.get('embedding_chunks',[])
        hyde_embedding_chunks = state.get('hyde_embedding_chunks',[])
        if not embedding_chunks:
            logger.info("向量召回结果为空")
            raise Exception("向量召回结果为空")
        if not hyde_embedding_chunks:
            logger.info("HyDE召回结果为空")
            raise Exception("HyDE召回结果为空")

        weight_embedding = [
            (embedding_chunks,1),
            (hyde_embedding_chunks,1)
        ]
        final_chunk_dict = {}
        for chunks, weight in weight_embedding:
            for idx,chunk in enumerate(chunks,start = 1):
                chunk_id = chunk.get('id')
                chunk_score = chunk.get('score') + weight / (idx+self.K)
                if chunk_id in final_chunk_dict:
                    final_chunk_dict[chunk_id]['score'] += chunk_score
                else:
                    chunk['score'] = chunk_score
                    final_chunk_dict[chunk_id] = chunk
        rrf_chunks = sorted(final_chunk_dict.values(), key=lambda x: x['score'], reverse=True)
        return {
            'rrf_chunks' : rrf_chunks[:len(embedding_chunks)]
        }

if __name__ == '__main__':
    init_state = {
        "embedding_chunks": [
        {
            "id": 468321334394046914,
            "entity_content": "brotherhak180烫金机-## 设备\n\n![安全使用设备，避免触电与受伤",
            "file_title": "hak180产品安全手册",
            "score": 0.8310319185256958,
            "source": "local"
        },
        {
            "id": 468321334394046901,
            "entity_content": "brotherhak180烫金机-## 设备\n\n![设备使用注意事项：防触电、防火、防烫伤，远离儿童",
            "file_title": "hak180产品安全手册",
            "score": 0.825168788433075,
            "source": "local"
        },
        {
            "id": 468321334394046912,
            "entity_content": "brotherhak180烫金机-## 设备\n\n![设备安全放置与使用指南](http://192.168.100.88:9000/my111/upload-images/c61a7f4e923881679f747508ae309c39dc221685344b068009256b1b3a40cc00",
            "file_title": "hak180产品安全手册",
            "score": 0.8122379779815674,
            "source": "local"
        },
        {
            "id": 468321334394046923,
            "entity_content": "brotherhak180烫金机-## 为设备选择一个安全的位置\n\n。](http://192.168.100.88:9000/my111/upload-images/8e839864036a7326885565163d99117ea943ecd29a656c85e7aa4052a9b9d28d",
            "file_title": "hak180产品安全手册",
            "score": 0.8088691234588623,
            "source": "local"
        },
        {
            "id": 468321334394046904,
            "entity_content": "brotherhak180烫金机-## 设备\n\n儎⑟ഴḽ䆜઀ᛞ࠽व䀜᪮儎⑟Ⲻ䇴༽䜞ԬȾ",
            "file_title": "hak180产品安全手册",
            "score": 0.7049253582954407,
            "source": "local"
        },
        {
            "id": 468321334394046893,
            "entity_content": "brotherhak180烫金机-## HAK 180 烫金机\n\n产品安全手册（简体中文）\n\n感谢您购买 HAK 180 烫金机。\n\n在使用本设备之前，请先阅读本手册，包括所有预防措施。阅读本手册后，请妥善保管。\n\n有关使用本设备的更多信息，请参阅使用说明书，其可在兄弟 (中国)商业有限公司技术服务支持网站 http://www.95105369.com/Web/Manuals.aspx 上找到。建议您先通读使用说明书，再使用本设备。\n\n如需获得常见问题解答、故障排除和说明书，请访问\n\nhttp://www.95105369.com。\n\n对于本设备所有者不遵守本指南中规定的说明操作而导致的损害，Brother 不承担任何责任。",
            "file_title": "hak180产品安全手册",
            "score": 0.7042595744132996,
            "source": "local"
        },
        {
            "id": 468321334394046911,
            "entity_content": "brotherhak180烫金机-## 设备\n\n•\t将本设备放置在平整、水平且稳定的表面上（如桌面），避免震动和冲击。\n\n•\t将本设备放置在通风良好的环境中。\n\n•\t为了防止人员受伤，请谨慎操作，避免将手指放置在图中所示的区域中。",
            "file_title": "hak180产品安全手册",
            "score": 0.7034879922866821,
            "source": "local"
        },
        {
            "id": 468321334394046919,
            "entity_content": "brotherhak180烫金机-## 为设备选择一个安全的位置\n\n![设备安全放置与电源使用注意事项](http://192.168.100.88:9000/my111/upload-images/cc5ee1ac24ebb2707d40dc7a234a8b243f55f5bf08fabc683859be6fdf096ffa",
            "file_title": "hak180产品安全手册",
            "score": 0.6972194314002991,
            "source": "local"
        },
        {
            "id": 468321334394046894,
            "entity_content": "brotherhak180烫金机-## HAK 180 烫金机\n\n•\t对于保养、调整或维修事宜，请联系 Brother 呼叫中心或您当地的Brother 经销商。\n\n•\t如果本设备工作不正常或发生任何错误，请关闭本设备，拔下所有电缆，然后联系 Brother 呼叫中心或您当地的 Brother 经销商。\n\n•\t本文档中提供的信息可能会随时更改，恕不另行通知。\n\n•\t严禁未经授权擅自复制或重制本文档的任何部分或全部内容。\n\n•\t请注意，对于使用通过本设备制作的产品造成的任何损坏或利润损失，或者故障、维修导致的数据消失或更改，或者第三方提出的任何索赔，我们不承担任何责任。",
            "file_title": "hak180产品安全手册",
            "score": 0.6955668926239014,
            "source": "local"
        },
        {
            "id": 468321334394046905,
            "entity_content": "brotherhak180烫金机-## 设备\n\n![起搏器用户慎用，注意高温与高压电风险",
            "file_title": "hak180产品安全手册",
            "score": 0.6924935579299927,
            "source": "local"
        }
    ],
        "hyde_embedding_chunks": [
        {
            "id": 468321334394046901,
            "entity_content": "brotherhak180烫金机-## 设备\n\n![设备使用注意事项：防触电、防火、防烫伤，远离儿童",
            "file_title": "hak180产品安全手册",
            "score": 0.8446421027183533,
            "source": "local"
        },
        {
            "id": 468321334394046912,
            "entity_content": "brotherhak180烫金机-## 设备\n\n![设备安全放置与使用指南](http://192.168.100.88:9000/my111/upload-images/c61a7f4e923881679f747508ae309c39dc221685344b068009256b1b3a40cc00",
            "file_title": "hak180产品安全手册",
            "score": 0.7171165347099304,
            "source": "local"
        },
        {
            "id": 468321334394046893,
            "entity_content": "brotherhak180烫金机-## HAK 180 烫金机\n\n产品安全手册（简体中文）\n\n感谢您购买 HAK 180 烫金机。\n\n在使用本设备之前，请先阅读本手册，包括所有预防措施。阅读本手册后，请妥善保管。\n\n有关使用本设备的更多信息，请参阅使用说明书，其可在兄弟 (中国)商业有限公司技术服务支持网站 http://www.95105369.com/Web/Manuals.aspx 上找到。建议您先通读使用说明书，再使用本设备。\n\n如需获得常见问题解答、故障排除和说明书，请访问\n\nhttp://www.95105369.com。\n\n对于本设备所有者不遵守本指南中规定的说明操作而导致的损害，Brother 不承担任何责任。",
            "file_title": "hak180产品安全手册",
            "score": 0.7149778008460999,
            "source": "local"
        },
        {
            "id": 468321334394046919,
            "entity_content": "brotherhak180烫金机-## 为设备选择一个安全的位置\n\n![设备安全放置与电源使用注意事项](http://192.168.100.88:9000/my111/upload-images/cc5ee1ac24ebb2707d40dc7a234a8b243f55f5bf08fabc683859be6fdf096ffa",
            "file_title": "hak180产品安全手册",
            "score": 0.7149463891983032,
            "source": "local"
        },
        {
            "id": 468321334394046911,
            "entity_content": "brotherhak180烫金机-## 设备\n\n•\t将本设备放置在平整、水平且稳定的表面上（如桌面），避免震动和冲击。\n\n•\t将本设备放置在通风良好的环境中。\n\n•\t为了防止人员受伤，请谨慎操作，避免将手指放置在图中所示的区域中。",
            "file_title": "hak180产品安全手册",
            "score": 0.7123882174491882,
            "source": "local"
        },
        {
            "id": 468321334394046923,
            "entity_content": "brotherhak180烫金机-## 为设备选择一个安全的位置\n\n。](http://192.168.100.88:9000/my111/upload-images/8e839864036a7326885565163d99117ea943ecd29a656c85e7aa4052a9b9d28d",
            "file_title": "hak180产品安全手册",
            "score": 0.7101499438285828,
            "source": "local"
        },
        {
            "id": 468321334394046914,
            "entity_content": "brotherhak180烫金机-## 设备\n\n![安全使用设备，避免触电与受伤",
            "file_title": "hak180产品安全手册",
            "score": 0.7084953188896179,
            "source": "local"
        },
        {
            "id": 468321334394046894,
            "entity_content": "brotherhak180烫金机-## HAK 180 烫金机\n\n•\t对于保养、调整或维修事宜，请联系 Brother 呼叫中心或您当地的Brother 经销商。\n\n•\t如果本设备工作不正常或发生任何错误，请关闭本设备，拔下所有电缆，然后联系 Brother 呼叫中心或您当地的 Brother 经销商。\n\n•\t本文档中提供的信息可能会随时更改，恕不另行通知。\n\n•\t严禁未经授权擅自复制或重制本文档的任何部分或全部内容。\n\n•\t请注意，对于使用通过本设备制作的产品造成的任何损坏或利润损失，或者故障、维修导致的数据消失或更改，或者第三方提出的任何索赔，我们不承担任何责任。",
            "file_title": "hak180产品安全手册",
            "score": 0.7011479735374451,
            "source": "local"
        },
        {
            "id": 468321334394046906,
            "entity_content": "brotherhak180烫金机-## 设备\n\n。](http://192.168.100.88:9000/my111/upload-images/501bb8d2d681e4502d87badb15a68939eadfa086d309c3599f1c36b0bc559177",
            "file_title": "hak180产品安全手册",
            "score": 0.6998234391212463,
            "source": "local"
        },
        {
            "id": 468321334394046902,
            "entity_content": "brotherhak180烫金机-## 设备\n\n。](http://192.168.100.88:9000/my111/upload-images/f3349cded08d6686a93d0a81b9a64ec1e50d9a82cbb88541b37027f085813a15",
            "file_title": "hak180产品安全手册",
            "score": 0.6985834240913391,
            "source": "local"
        }
    ]
    }
    node_search_embedding = NodeRrf()
    result = node_search_embedding(init_state)
    logger.info(json_format(result))