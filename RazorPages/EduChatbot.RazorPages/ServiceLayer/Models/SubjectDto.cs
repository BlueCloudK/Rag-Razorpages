using System.Collections.Generic;

namespace ServiceLayer.Models
{
    public class SubjectDto
    {
        public int Id { get; set; }
        public string Name { get; set; } = string.Empty;
        public string Code { get; set; } = string.Empty;
        public int? OrganizationId { get; set; }
        public string OrganizationName { get; set; } = string.Empty;
        public string CurrentUserRole { get; set; } = string.Empty;
        public List<DocumentDto> Documents { get; set; } = new();
    }
}
