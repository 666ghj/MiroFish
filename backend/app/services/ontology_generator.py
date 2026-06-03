"""
Dịch vụ tạo Ontology (Hệ thực thể / Quan hệ)
API 1: Phân tích nội dung văn bản, khởi tạo các định nghĩa về loại thực thể và quan hệ phù hợp cho việc mô phỏng mạng xã hội
"""

import json
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient


# System prompt dùng cho việc tự động sinh Ontology
# ONTOLOGY_SYSTEM_PROMPT = """You are a professional Knowledge Graph Ontology Design Expert. Your task is to analyze the given text content and simulation requirements to design entity types and relationship types suitable for **social media public opinion simulation**.

# **IMPORTANT: You must output valid JSON format data only. Do not include any other text.**

# ## Core Task Background

# We are building a social media public opinion simulation system. In this system:
# - Each entity is an "account" or "subject" capable of speaking, interacting, and spreading information on social media.
# - Entities influence, forward, comment on, and respond to each other.
# - We need to simulate the reactions of all parties and the paths of information dissemination during public opinion events.

# Therefore, **entities must be real-world subjects capable of speaking and interacting on social media**:

# **CAN BE**:
# - Specific individuals (public figures, parties involved, opinion leaders, experts, ordinary people).
# - Companies and enterprises (including their official accounts).
# - Organizations (universities, associations, NGOs, labor unions, etc.).
# - Government departments and regulatory agencies.
# - Media outlets (newspapers, TV stations, independent media, websites).
# - Social media platforms themselves.
# - Representatives of specific groups (e.g., alumni associations, fan clubs, rights protection groups).

# **CANNOT BE**:
# - Abstract concepts (e.g., "public opinion", "emotion", "trend").
# - Themes/Topics (e.g., "academic integrity", "education reform").
# - Viewpoints/Attitudes (e.g., "supporters", "opponents").

# ## Output Format

# Please output in JSON format with the following structure:

# ```json
# {
#     "entity_types": [
#         {
#             "name": "Entity type name (English, PascalCase)",
#             "description": "Short description (English, max 100 characters)",
#             "attributes": [
#                 {
#                     "name": "Attribute name (English, snake_case)",
#                     "type": "text",
#                     "description": "Attribute description"
#                 }
#             ],
#             "examples": ["Example Entity 1", "Example Entity 2"]
#         }
#     ],
#     "edge_types": [
#         {
#             "name": "Relationship type name (English, UPPER_SNAKE_CASE)",
#             "description": "Short description (English, max 100 characters)",
#             "source_targets": [
#                 {"source": "Source entity type", "target": "Target entity type"}
#             ],
#             "attributes": []
#         }
#     ],
#     "analysis_summary": "Brief analysis of the text content (in Vietnamese)"
# }
# ```

# ## Design Guidelines (Extremely Important!)

# ### 1. Entity Type Design - Strict Compliance Required

# **Quantity Requirement: Must be EXACTLY 10 entity types.**

# **Hierarchy Requirements (Must include both specific types and fallback types):**

# Your 10 entity types must include the following layers:

# A. **Fallback Types (Required, place as the last 2 in the list)**:
#    - `Person`: The fallback type for any individual natural person. Use this when a person does not fit into other specific person types.
#    - `Organization`: The fallback type for any organization or institution. Use this when an organization does not fit into other specific organizational types.

# B. **Specific Types (8 types, designed based on text content)**:
#    - Design more specific types targeting the main roles appearing in the text.
#    - Example: For academic events, use `Student`, `Professor`, `University`
#    - VExample: For business events, use `Company`, `CEO`, `Employee`

# **Why fallback types are needed:**
# - Various people appear in texts (e.g., "primary school teacher", "passerby", "netizen").
# - Without a specific match, they should be categorized under `Person`.
# - Similarly, small organizations or temporary groups should fall under `Organization`.

# **Specific Type Design Principles:**
# - Identify high-frequency or critical roles from the text.
# - Each specific type should have clear boundaries to avoid overlap.
# - The description must clearly state the difference between this type and the fallback type.

# ### 2. Relationship Type Design

# - Quantity: 6-10 types.
# - Relationships should reflect real-world connections in social media interactions.
# - Ensure `source_targets` cover your defined entity types.

# ### 3. Attribute Design

# - 1-3 key attributes per entity type.
# - **NOTE**: Do NOT use `name`, `uuid`, `group_id`, `created_at` or `summary` as attribute names (these are system reserved words).
# - Recommended: `full_name`, `title`, `role`, `position`, `location`, `description, etc.

# ## Entity Type References

# - Individuals (Specific): Student, Professor, Journalist, Celebrity, Executive, Official, Lawyer, Doctor.
# - Individuals (Fallback): Person.
# - Organizations (Specific): University, Company, GovernmentAgency, MediaOutlet, Hospital, School, NGO.
# - Organizations (Fallback): Organization.

# ## Relationship Type References

# WORKS_FOR, STUDIES_AT, AFFILIATED_WITH, REPRESENTS, REGULATES, REPORTS_ON, COMMENTS_ON, RESPONDS_TO, SUPPORTS, OPPOSES, COLLABORATES_WITH, COMPETES_WITH.
# """

ONTOLOGY_SYSTEM_PROMPT = """Bạn là một chuyên gia thiết kế Bản thể học (Ontology) cho Biểu đồ tri thức chuyên nghiệp. Nhiệm vụ của bạn là phân tích nội dung văn bản và yêu cầu mô phỏng được cung cấp để thiết kế các loại thực thể và loại quan hệ phù hợp cho việc **mô phỏng dư luận trên mạng xã hội**.

**QUAN TRỌNG: Bạn phải xuất dữ liệu ở định dạng JSON hợp lệ, không xuất thêm bất kỳ nội dung nào khác.**

## Bối cảnh nhiệm vụ cốt lõi
- Chúng tôi đang xây dựng một hệ thống mô phỏng dư luận mạng xã hội. Trong hệ thống này:
- Mỗi thực thể là một "tài khoản" hoặc "chủ thể" có thể phát ngôn, tương tác và lan truyền thông tin trên mạng xã hội.
- Các thực thể sẽ ảnh hưởng, chia sẻ, bình luận và phản hồi lẫn nhau.
- Chúng tôi cần mô phỏng phản ứng của các bên và lộ trình lan truyền thông tin trong các sự kiện dư luận.

Do đó, **thực thể phải là những chủ thể tồn tại thực tế, có khả năng phát ngôn và tương tác trên mạng xã hội**:

**CÓ THỂ LÀ**:
- Cá nhân cụ thể (người công chúng, bên liên quan, người dẫn dắt dư luận, chuyên gia, người bình thường).
- Công ty, doanh nghiệp (bao gồm cả tài khoản chính thức của họ).
- Tổ chức (trường đại học, hiệp hội, NGO, công đoàn, v.v.).
- Cơ quan chính phủ, cơ quan quản lý.
- Cơ quan truyền thông (báo chí, đài truyền hình, tự truyền thông, trang web).
- Bản thân nền tảng mạng xã hội.
- Đại diện nhóm cụ thể (như hội cựu sinh viên, nhóm người hâm mộ, nhóm bảo vệ quyền lợi, v.v.).

**KHÔNG THỂ LÀ**:
- Khái niệm trừu tượng (như "dư luận", "cảm xúc", "xu hướng").
- Chủ đề/Vấn đề (như "liêm chính học thuật", "cải cách giáo dục").
- Quan điểm/Thái độ (như "bên ủng hộ", "bên phản đối").

## Định dạng đầu ra

Hãy trả về dưới định dạng JSON, bao gồm cấu trúc sau:

```json
{
    "entity_types": [
        {
            "name": "Tên loại thực thể (Tiếng Anh, PascalCase)",
            "description": "Mô tả ngắn gọn (Tiếng Anh, không quá 100 ký tự)",
            "attributes": [
                {
                    "name": "Tên thuộc tính (Tiếng Anh, snake_case)",
                    "type": "text",
                    "description": "Mô tả thuộc tính"
                }
            ],
            "examples": ["Thực thể ví dụ 1", "Thực thể ví dụ 2"]
        }
    ],
    "edge_types": [
        {
            "name": "Tên loại quan hệ (Tiếng Anh, UPPER_SNAKE_CASE)",
            "description": "Mô tả ngắn gọn (Tiếng Anh, không quá 100 ký tự)",
            "source_targets": [
                {"source": "Loại thực thể nguồn", "target": "Loại thực thể đích"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "Phân tích ngắn gọn nội dung văn bản (bằng tiếng Việt)"
}
```

## Hướng dẫn thiết kế (Cực kỳ quan trọng!)

### 1. Thiết kế loại thực thể - Phải tuân thủ nghiêm ngặt

**Yêu cầu số lượng: Phải có CHÍNH XÁC 10 loại thực thể.**

**Yêu cầu về cấu trúc phân cấp (Phải bao gồm cả loại cụ thể và loại dự phòng):**

10 loại thực thể của bạn phải bao gồm cấp độ sau:

A. **Loại bao quát (Fallback Types) (BẮT BUỘC, phải nằm ở 2 vị trí cuối cùng trong mảng)**:
   - `Person`: Là loại bao quát cho MỌI cá nhân tự nhiên. Nếu một người không thuộc các loại cụ thể ở trên, người đó sẽ thuộc `Person`.
   - `Organization`: Là loại bao quát cho MỌI tổ chức. Đặc trưng cho các tổ chức nhỏ hoặc không phù hợp với các loại tổ chức cụ thể khác.

B. **Loại cụ thể (8 loại, phụ thuộc vào nội dung văn bản)**:
   - Thiết kế các loại cụ thể cho các vai trò chính được nhắc đến nhiều nhất trong văn bản.
   - Ví dụ: Nếu văn bản nói về scandal trường học, có thể có: `Student`, `Professor`, `University`
   - Ví dụ: Nếu văn bản là câu chuyện kinh doanh, có thể có: `Company`, `CEO`, `Employee`

**Tại sao cần các loại Bao quát (Fallback):**
- Văn bản thường chứa các thông tin như "giáo viên tiểu học", "một người qua đường", "một cư dân mạng"
- Nếu không có loại được định nghĩa riêng cho họ, họ nên thuộc về loại `Person`
- Tương tự, tổ chức nhỏ bé hoặc nhóm học tập tạm thời nên thuộc `Organization`

**Nguyên tắc cho các loại Cụ thể:**
- Nhận diện các vai trò xuất hiện với tần suất cao hoặc quan trọng từ văn bản.
- Mỗi loại nên có một ranh giới rõ ràng, không bị chồng chéo.
- Phần description phải giải thích rõ sự khác biệt giữa loại này và loại bao quát.

### 2. Thiết kế Cạnh/Quan hệ (Edge Types)

- Số lượng: Khoảng 6-10 loại quan hệ
- Các mối quan hệ này phải giải thích và gắn kết được hành vi tương tác trên mạng xã hội của các nhân vật.
- Đảm bảo mapping quan hệ hai chiều `source_targets` khớp với các thực thể phía trên.

### 3. Thiết kế Thuộc tính (Attributes)

- Mỗi loại thực thể cần 1-3 thuộc tính chính để làm rõ nhân thân.
- **CHÚ Ý**: Không sử dụng các ID nội bộ làm thuộc tính như `name`, `uuid`, `group_id`, `created_at`, `summary` (chúng là từ khóa hệ thống).
- Khuyên dùng: `full_name`, `title`, `role`, `position`, `location`, `description`,...

## Loại Thực thể tham khảo 

- Nhóm cá nhân (Cụ thể): Student, Professor, Journalist, Celebrity, Executive, Official, Lawyer, Doctor.
- Nhóm cá nhân (Bao quát): Person.
- Nhóm tổ chức (Cụ thể): University, Company, GovernmentAgency, MediaOutlet, Hospital, School, NGO.
- Nhóm tổ chức (Bao quát): Organization.

## Tham khảo loại quan hệ

WORKS_FOR, STUDIES_AT, AFFILIATED_WITH, REPRESENTS, REGULATES, REPORTS_ON, COMMENTS_ON, RESPONDS_TO, SUPPORTS, OPPOSES, COLLABORATES_WITH, COMPETES_WITH.
"""


class OntologyGenerator:
    """
    Trình khởi tạo Ontology
    Phân tích nội dung đoạn văn bản truyền vào, sau đó tự động suy luận ra định nghĩa của các loại Thực thể và Mối quan hệ
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
    
    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Khởi tạo định nghĩa Ontology
        
        Args:
            document_texts: Danh sách mảng các văn bản nội dung nguồn
            simulation_requirement: Chuỗi mô tả nhu cầu mô phỏng của người dùng
            additional_context: Văn bản cung cấp thêm các ngữ cảnh phụ (nếu có)
            
        Returns:
            Dictionary gồm cấu trúc Ontology (entity_types, edge_types v.v.)
        """
        # Tạo câu lệnh Prompt gửi cho mô hình LLM
        user_message = self._build_user_message(
            document_texts, 
            simulation_requirement,
            additional_context
        )
        
        messages = [
            {"role": "system", "content": ONTOLOGY_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]
        
        # Gửi request đến LLM
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,        
        )
        
        # Kiểm tra tính hợp lệ và xử lý tinh chỉnh kết quả đầu ra
        result = self._validate_and_process(result)
        
        return result
    
    # Định mức giới hạn độ dài ký tự tối đa của đoạn văn bản có thể gửi cho LLM (10 vạn chữ)
    MAX_TEXT_LENGTH_FOR_LLM = 100000
    
    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """Ghép các thông tin đầu vào thành User Prompt hoàn chỉnh để gửi tới LLM"""
        
        # Gộp tất cả các đoạn văn bản thành một string duy nhất
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)
        
        # Nếu vượt quá giới hạn tối đa, thực hiện cắt bớt (Việc này chỉ ảnh hưởng prompt gửi nhận diện Ontology, không ảnh hưởng thư viện Graph building ở sau)
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += f"\n\n...(Original text is {original_length} characters long; the first {self.MAX_TEXT_LENGTH_FOR_LLM} characters have been proactively truncated for Ontology analysis)..."

#         message = f"""## Simulation Requirements

# {simulation_requirement}

# ## Document Content

# {combined_text}
# """
        
#         if additional_context:
#             message += f"""
# ## Additional Context

# {additional_context}
# """
        
#         message += """
# Based on the content above, please design entity types and relationship types suitable for social media public opinion simulation.

# **Rules that MUST be followed**:
# 1. You must output EXACTLY 10 entity types.
# 2. The last 2 types must be fallback types: Person (individual fallback) and Organization (organization fallback).
# 3. The first 8 types should be specific types designed based on the text content.
# 4. All entity types must be real-world subjects capable of speaking/interacting; they cannot be abstract concepts.
# 5. Attribute names cannot use reserved words like name, uuid, or group_id; use alternatives like full_name, org_name, etc.
# """
        
        message = f"""## Yêu cầu mô phỏng

{simulation_requirement}

## Nội dung tài liệu

{combined_text}
"""
        
        if additional_context:
            message += f"""
## Giải thích bổ sung

{additional_context}
"""
        
        message += """
Dựa trên các nội dung trên, hãy thiết kế các loại thực thể và loại quan hệ phù hợp cho việc mô phỏng dư luận xã hội.

**Các quy tắc BẮT BUỘC phải tuân thủ**:
1. Phải xuất chính xác 10 loại thực thể.
2. 2 loại cuối cùng phải là loại dự phòng: Person (Cá nhân dự phòng) và Organization (Tổ chức dự phòng).
3. 8 loại đầu tiên là các loại cụ thể được thiết kế dựa trên nội dung văn bản.
4. Tất cả các loại thực thể phải là những chủ thể có thể phát ngôn trong thực tế, không được là các khái niệm trừu tượng.
5. Tên thuộc tính không được sử dụng các từ khóa hệ thống như name, uuid, group_id; hãy thay thế bằng full_name, org_name, v.v.
"""
        
        return message
    
    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Tiền kiểm tra tính trọn vẹn và cấu trúc của dữ liệu phản hồi JSON"""
        
        # Đảm bảo các thuộc tính mảng bắt buộc phải xuất hiện
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""
        
        # Tiền xử lý để loại thực thể hợp lệ
        for entity in result["entity_types"]:
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # Cắt ngắn description nếu vượt quá độ dài tối đa 100 character
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."
        
        # Tiền xử lý để loại quan hệ hợp lệ
        for edge in result["edge_types"]:
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."
        
        # Ràng buộc số lượng đầu ra của API Zep: Tối đa 10 loại thực thể tự tuỳ chỉnh, và Tối đa 10 loại cạnh quan hệ tùy chỉnh
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10
        
        # Khai báo định nghĩa về 2 đối tượng bao quát (fallback) mặc định
        person_fallback = {
            "name": "Person",
            "description": "Any individual person not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "role", "type": "text", "description": "Role or occupation"}
            ],
            "examples": ["ordinary citizen", "anonymous netizen"]
        }
        
        organization_fallback = {
            "name": "Organization",
            "description": "Any organization not fitting other specific organization types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "org_type", "type": "text", "description": "Type of organization"}
            ],
            "examples": ["small business", "community group"]
        }
        
        # Sàng lọc kiểm tra xem kết quả đầu ra đã chứa sẵn các danh mục rỗng (fallback) ở vị trí chuẩn chưa
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names
        
        # Danh sách cần phải gán bù vào
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)
        
        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)
            
            # Nếu thêm vào bị quá giới hạn 10 loại, cần phải loại bỏ bớt các loại Entity đằng trước
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                # Tính lượng bị thừa ra so với hạn mức (Để bỏ đi)
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                # Bỏ bớt n vị trí tính từ cuối mảng (Đảm bảo chừa lại nhóm các thực thể cụ thể đã phân tích ở trên)
                result["entity_types"] = result["entity_types"][:-to_remove]
            
            # Nối cụm Fallbacks vừa khởi tạo vào cuối chuỗi
            result["entity_types"].extend(fallbacks_to_add)
        
        # Đảm bảo phòng thủ một lần cuối cùng không có quá 10 Element Array
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]
        
        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]
        
        return result
    
    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        Dựng (Generate) file Script với nội dung Python Class tương ứng khai báo dữ liệu Ontology để máy đọc (Tương tự như file ontology.py)
        
        Args:
            ontology: Từ điển định nghĩa Ontology
            
        Returns:
            Chuỗi đoạn code File Python cần tạo để lưu
        """
        code_lines = [
            '"""',
            'Custom Entity Type Definitions',
            'Automatically generated by MiroFish for social media public opinion simulation',
            '"""',
            '',
            'from pydantic import Field',
            'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
            '',
            '',
            '# ============== Entity Type Definitions ==============',
            '',
        ]
        
        # Khởi tạo các đoạn mã tương ứng với Định nghĩa thực thể Entity
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")
            
            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        code_lines.append('# ============== Relationship Type Definitions ==============')
        code_lines.append('')
        
        # Khởi tạo các đoạn mã tạo lập Relationship (Edges)
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            # Đổi cấu trúc tên format Class theo chuẩn PascalCase của Python
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")
            
            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        # Tự động kết xuất ra dictionary mapping từ Tên Loại - sang class Object
        code_lines.append('# ============== Type Configuration ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')
        
        # Cấu hình mảng mapping giới hạn Source->Target cho từng cạnh (Edges source_targets config)
        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')
        
        return '\n'.join(code_lines)

