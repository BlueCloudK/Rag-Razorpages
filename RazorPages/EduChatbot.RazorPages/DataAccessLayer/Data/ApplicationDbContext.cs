using DataAccessLayer.Models;
using Microsoft.AspNetCore.Identity.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore;

namespace DataAccessLayer.Data
{
    public class ApplicationDbContext : IdentityDbContext<ApplicationUser>
    {
        public ApplicationDbContext(DbContextOptions<ApplicationDbContext> options)
            : base(options)
        {
        }

        public DbSet<Subject> Subjects { get; set; }
        public DbSet<Document> Documents { get; set; }
        public DbSet<ChatSession> ChatSessions { get; set; }
        public DbSet<ChatMessage> ChatMessages { get; set; }
        public DbSet<SubjectMembership> SubjectMemberships { get; set; }
        public DbSet<SubscriptionPlan> SubscriptionPlans { get; set; }
        public DbSet<UserSubscription> UserSubscriptions { get; set; }
        public DbSet<QuestionUsage> QuestionUsages { get; set; }
        public DbSet<Organization> Organizations { get; set; }
        public DbSet<OrganizationMember> OrganizationMembers { get; set; }
        public DbSet<OrganizationSubscription> OrganizationSubscriptions { get; set; }
        public DbSet<BillingInvoice> BillingInvoices { get; set; }
        public DbSet<CheckoutSession> CheckoutSessions { get; set; }
        public DbSet<AuditLog> AuditLogs { get; set; }

        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);

            modelBuilder.Entity<SubjectMembership>()
                .HasIndex(m => new { m.SubjectId, m.UserId })
                .IsUnique();

            modelBuilder.Entity<SubscriptionPlan>()
                .HasIndex(p => p.Name)
                .IsUnique();

            modelBuilder.Entity<QuestionUsage>()
                .HasIndex(u => new { u.UserId, u.UsageDate })
                .IsUnique();

            modelBuilder.Entity<QuestionUsage>()
                .HasIndex(u => new { u.OrganizationId, u.UsageDate });

            modelBuilder.Entity<Organization>()
                .HasIndex(o => o.Slug)
                .IsUnique();

            modelBuilder.Entity<OrganizationMember>()
                .HasIndex(m => new { m.OrganizationId, m.UserId })
                .IsUnique();

            modelBuilder.Entity<OrganizationSubscription>()
                .HasIndex(s => new { s.OrganizationId, s.IsActive });

            modelBuilder.Entity<CheckoutSession>()
                .HasIndex(s => s.ReferenceCode)
                .IsUnique();

            modelBuilder.Entity<BillingInvoice>()
                .Property(i => i.Amount)
                .HasPrecision(18, 2);

            modelBuilder.Entity<CheckoutSession>()
                .Property(s => s.Amount)
                .HasPrecision(18, 2);

            modelBuilder.Entity<ChatSession>()
                .HasIndex(s => new { s.SubjectId, s.UserId });

            modelBuilder.Entity<Document>()
                .HasIndex(d => d.UploadedByUserId);

            modelBuilder.Entity<AuditLog>()
                .HasIndex(l => l.CreatedAt);

            modelBuilder.Entity<AuditLog>()
                .HasIndex(l => new { l.OrganizationId, l.CreatedAt });

            modelBuilder.Entity<AuditLog>()
                .HasIndex(l => new { l.SubjectId, l.CreatedAt });

            modelBuilder.Entity<Subject>()
                .HasIndex(s => s.OrganizationId);

            modelBuilder.Entity<SubjectMembership>()
                .HasOne(m => m.Subject)
                .WithMany()
                .HasForeignKey(m => m.SubjectId)
                .OnDelete(DeleteBehavior.Cascade);

            modelBuilder.Entity<SubjectMembership>()
                .HasOne(m => m.User)
                .WithMany(u => u.SubjectMemberships)
                .HasForeignKey(m => m.UserId)
                .OnDelete(DeleteBehavior.Cascade);

            modelBuilder.Entity<ChatSession>()
                .HasOne(s => s.User)
                .WithMany()
                .HasForeignKey(s => s.UserId)
                .OnDelete(DeleteBehavior.SetNull);

            modelBuilder.Entity<Document>()
                .HasOne(d => d.UploadedByUser)
                .WithMany()
                .HasForeignKey(d => d.UploadedByUserId)
                .OnDelete(DeleteBehavior.SetNull);

            modelBuilder.Entity<Subject>()
                .HasOne(s => s.Organization)
                .WithMany(o => o.Subjects)
                .HasForeignKey(s => s.OrganizationId)
                .OnDelete(DeleteBehavior.SetNull);

            modelBuilder.Entity<OrganizationMember>()
                .HasOne(m => m.Organization)
                .WithMany(o => o.Members)
                .HasForeignKey(m => m.OrganizationId)
                .OnDelete(DeleteBehavior.Cascade);

            modelBuilder.Entity<OrganizationMember>()
                .HasOne(m => m.User)
                .WithMany()
                .HasForeignKey(m => m.UserId)
                .OnDelete(DeleteBehavior.Cascade);

            modelBuilder.Entity<OrganizationSubscription>()
                .HasOne(s => s.Organization)
                .WithMany(o => o.Subscriptions)
                .HasForeignKey(s => s.OrganizationId)
                .OnDelete(DeleteBehavior.Cascade);

            modelBuilder.Entity<QuestionUsage>()
                .HasOne(u => u.Organization)
                .WithMany()
                .HasForeignKey(u => u.OrganizationId)
                .OnDelete(DeleteBehavior.SetNull);
        }
    }
}
