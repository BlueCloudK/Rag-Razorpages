using System.Collections.Generic;

namespace ServiceLayer.Models
{
    public class LoginInput
    {
        public string Email { get; set; } = string.Empty;
        public string Password { get; set; } = string.Empty;
        public bool RememberMe { get; set; }
        public string? ReturnUrl { get; set; }
    }

    public class RegisterInput
    {
        public string FullName { get; set; } = string.Empty;
        public string Email { get; set; } = string.Empty;
        public string Password { get; set; } = string.Empty;
        public string ConfirmPassword { get; set; } = string.Empty;
    }

    public class AuthResult
    {
        public bool Success { get; set; }
        public string Message { get; set; } = string.Empty;
        public List<string> Errors { get; set; } = new();
    }

    public class SubscriptionStatusDto
    {
        public string PlanName { get; set; } = "Free";
        public int QuestionsUsedToday { get; set; }
        public int MaxQuestionsPerDay { get; set; }
        public int DocumentsUsed { get; set; }
        public int MaxDocuments { get; set; }
        public int SubjectsUsed { get; set; }
        public int MaxSubjects { get; set; }
        public int MembersUsed { get; set; }
        public int MaxMembers { get; set; }
        public int MaxFileSizeMb { get; set; }
        public bool AllowGemini { get; set; }
        public bool IsUnlimited { get; set; }
        public bool BypassesQuota { get; set; }
    }
}
