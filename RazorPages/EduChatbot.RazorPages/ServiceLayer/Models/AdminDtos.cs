using System.Collections.Generic;

namespace ServiceLayer.Models
{
    public class AdminUserDto
    {
        public string UserId { get; set; } = string.Empty;
        public string Email { get; set; } = string.Empty;
        public string FullName { get; set; } = string.Empty;
        public string Role { get; set; } = string.Empty;
        public string OrganizationRole { get; set; } = string.Empty;
    }

    public class AdminUserManagementDto
    {
        public List<AdminUserDto> Users { get; set; } = new();
        public List<string> Roles { get; set; } = new();
    }

    public class AdminEditUserInput
    {
        public string UserId { get; set; } = string.Empty;
        public string Role { get; set; } = string.Empty;
    }

    public class AdminCreateUserInput
    {
        public string Email { get; set; } = string.Empty;
        public string FullName { get; set; } = string.Empty;
        public string Password { get; set; } = string.Empty;
        public string Role { get; set; } = string.Empty;
    }

    public class SubjectMembershipAdminDto
    {
        public int Id { get; set; }
        public int SubjectId { get; set; }
        public string UserId { get; set; } = string.Empty;
        public string SubjectName { get; set; } = string.Empty;
        public string UserEmail { get; set; } = string.Empty;
        public string RoleInSubject { get; set; } = string.Empty;
        public bool IsCurrentUser { get; set; }
        public bool IsSystemAdmin { get; set; }
    }

    public class AdminSubjectOptionDto
    {
        public int Id { get; set; }
        public string Name { get; set; } = string.Empty;
    }

    public class AdminMembershipManagementDto
    {
        public List<SubjectMembershipAdminDto> Memberships { get; set; } = new();
        public List<AdminSubjectOptionDto> Subjects { get; set; } = new();
        public List<AdminUserDto> Users { get; set; } = new();
    }

    public class AdminMembershipInput
    {
        public int SubjectId { get; set; }
        public string UserId { get; set; } = string.Empty;
        public string RoleInSubject { get; set; } = string.Empty;
    }
}
