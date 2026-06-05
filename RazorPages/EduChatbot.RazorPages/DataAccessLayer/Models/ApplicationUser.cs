using Microsoft.AspNetCore.Identity;

namespace DataAccessLayer.Models
{
    public class ApplicationUser : IdentityUser
    {
        public string FullName { get; set; } = string.Empty;
        public ICollection<SubjectMembership>? SubjectMemberships { get; set; }
        public ICollection<UserSubscription>? UserSubscriptions { get; set; }
        public ICollection<QuestionUsage>? QuestionUsages { get; set; }
    }
}
