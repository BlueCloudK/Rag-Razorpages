namespace DataAccessLayer.Models
{
    public class SubscriptionPlan
    {
        public int Id { get; set; }
        public string Name { get; set; } = string.Empty;
        public int MaxQuestionsPerDay { get; set; }
        public int MaxDocuments { get; set; }
        public int MaxFileSizeMb { get; set; }
        public int MaxSubjects { get; set; }
        public int MaxMembers { get; set; }
        public bool AllowGemini { get; set; }
        public bool IsUnlimited { get; set; }
        public ICollection<UserSubscription>? UserSubscriptions { get; set; }
        public ICollection<OrganizationSubscription>? OrganizationSubscriptions { get; set; }
    }
}
