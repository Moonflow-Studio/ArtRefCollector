"""Functional category definitions for art reference classification."""

from models.schemas import FunctionalCategory

SECTION_DEFINITIONS: list[FunctionalCategory] = [
    FunctionalCategory(
        id="mood",
        name="整体氛围 / Mood",
        description="用于表达设定整体气质、情绪、压迫感、神秘感、冷暖关系等。",
    ),
    FunctionalCategory(
        id="architecture",
        name="建筑语言 / Architecture",
        description="建筑轮廓、门窗、屋顶、结构、立面、尺度和风格来源。",
    ),
    FunctionalCategory(
        id="urban_layout",
        name="城市布局 / Urban Layout",
        description="街道密度、空间层级、聚落结构、城市剖面、天际线。",
    ),
    FunctionalCategory(
        id="interior",
        name="室内空间 / Interior",
        description="室内结构、陈设、尺度、空间纵深、照明环境。",
    ),
    FunctionalCategory(
        id="materials",
        name="材质纹理 / Materials",
        description="石材、金属、木材、织物、雪、锈蚀、污渍、壁画等。",
    ),
    FunctionalCategory(
        id="color_lighting",
        name="色彩光照 / Color & Lighting",
        description="主色、辅色、冷暖关系、局部光源、明暗结构。",
    ),
    FunctionalCategory(
        id="costume_character",
        name="服装角色 / Costume & Character",
        description="人物轮廓、服装层次、身份区分、材质、配饰。",
    ),
    FunctionalCategory(
        id="props",
        name="道具器物 / Props",
        description="仪式器具、工具、武器、生活物件、容器、家具。",
    ),
    FunctionalCategory(
        id="symbols_patterns",
        name="符号图案 / Symbols & Patterns",
        description="宗教符号、纹样、徽章、壁画、标识、文字系统。",
    ),
    FunctionalCategory(
        id="tech_machinery",
        name="技术与机械 / Tech & Machinery",
        description="管道、机器、线路、仪表、发动机、工业结构件。",
    ),
    FunctionalCategory(
        id="landscape",
        name="自然环境 / Landscape",
        description="地貌、气候、植被、山谷、雪地、水体、天空。",
    ),
    FunctionalCategory(
        id="composition",
        name="构图参考 / Composition",
        description="镜头、透视、空间压迫感、纵深、视觉重心、画面组织。",
    ),
    FunctionalCategory(
        id="anti_reference",
        name="负面参考 / Anti-reference",
        description="看起来相关但不应采用的方向，用于提醒避免跑偏。",
    ),
]

CATEGORY_MAP = {cat.id: cat for cat in SECTION_DEFINITIONS}
CATEGORY_IDS = [cat.id for cat in SECTION_DEFINITIONS]
