using System;
using System.Linq;
using System.Threading.Tasks;
using DataAccessLayer.Data;
using DataAccessLayer.Models;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace ServiceLayer.Services
{
    public static class DatabaseInitializer
    {
        public static async Task InitializeEduChatbotDatabaseAsync(this IServiceProvider services, bool seedDemoUsers = false)
        {
            using var scope = services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<ApplicationDbContext>();
            await db.Database.MigrateAsync();
            await db.Database.ExecuteSqlRawAsync("""
                IF COL_LENGTH('Documents', 'ChunkCount') IS NULL
                    ALTER TABLE Documents ADD ChunkCount int NOT NULL CONSTRAINT DF_Documents_ChunkCount DEFAULT 0;
                IF COL_LENGTH('Documents', 'IndexStatus') IS NULL
                    ALTER TABLE Documents ADD IndexStatus nvarchar(50) NOT NULL CONSTRAINT DF_Documents_IndexStatus DEFAULT N'Pending';
                IF COL_LENGTH('Documents', 'IndexMessage') IS NULL
                    ALTER TABLE Documents ADD IndexMessage nvarchar(1000) NULL;
                IF COL_LENGTH('Documents', 'IndexedAt') IS NULL
                    ALTER TABLE Documents ADD IndexedAt datetime2 NULL;
            """);
            await EnsureSaaSSchemaAsync(db);

            await SeedPlansAsync(db);
            await SeedRolesAsync(scope.ServiceProvider.GetRequiredService<RoleManager<IdentityRole>>());
            await SeedDefaultOrganizationAsync(db);

            if (seedDemoUsers)
            {
                await SeedDemoUsersAsync(
                    db,
                    scope.ServiceProvider.GetRequiredService<UserManager<ApplicationUser>>());
            }
        }

        private static async Task SeedPlansAsync(ApplicationDbContext db)
        {
            await UpsertPlanAsync(db, AuthConstants.Free, 20, 3, 5, 1, 30, allowGemini: false, isUnlimited: false);
            await UpsertPlanAsync(db, AuthConstants.Pro, 300, 50, 50, 10, 120, allowGemini: true, isUnlimited: false);
            await UpsertPlanAsync(db, AuthConstants.Organization, 10000, 10000, 200, 10000, 10000, allowGemini: true, isUnlimited: true);
            await db.SaveChangesAsync();
        }

        private static async Task UpsertPlanAsync(
            ApplicationDbContext db,
            string name,
            int questions,
            int documents,
            int fileSizeMb,
            int subjects,
            int members,
            bool allowGemini,
            bool isUnlimited)
        {
            var plan = await db.SubscriptionPlans.FirstOrDefaultAsync(p => p.Name == name);
            if (plan == null)
            {
                db.SubscriptionPlans.Add(new SubscriptionPlan
                {
                    Name = name,
                    MaxQuestionsPerDay = questions,
                    MaxDocuments = documents,
                    MaxFileSizeMb = fileSizeMb,
                    MaxSubjects = subjects,
                    MaxMembers = members,
                    AllowGemini = allowGemini,
                    IsUnlimited = isUnlimited
                });
                return;
            }

            plan.MaxQuestionsPerDay = questions;
            plan.MaxDocuments = documents;
            plan.MaxFileSizeMb = fileSizeMb;
            plan.MaxSubjects = subjects;
            plan.MaxMembers = members;
            plan.AllowGemini = allowGemini;
            plan.IsUnlimited = isUnlimited;
        }

        private static async Task EnsureSaaSSchemaAsync(ApplicationDbContext db)
        {
            await db.Database.ExecuteSqlRawAsync("""
                IF OBJECT_ID(N'[Organizations]', N'U') IS NULL
                BEGIN
                    CREATE TABLE [Organizations] (
                        [Id] int NOT NULL IDENTITY,
                        [Name] nvarchar(160) NOT NULL,
                        [Slug] nvarchar(80) NOT NULL,
                        [IsActive] bit NOT NULL CONSTRAINT [DF_Organizations_IsActive] DEFAULT CAST(1 AS bit),
                        [CreatedAt] datetime2 NOT NULL CONSTRAINT [DF_Organizations_CreatedAt] DEFAULT SYSUTCDATETIME(),
                        CONSTRAINT [PK_Organizations] PRIMARY KEY ([Id])
                    );
                    CREATE UNIQUE INDEX [IX_Organizations_Slug] ON [Organizations] ([Slug]);
                END;

                IF COL_LENGTH('Subjects', 'OrganizationId') IS NULL
                    ALTER TABLE [Subjects] ADD [OrganizationId] int NULL;
                IF COL_LENGTH('QuestionUsages', 'OrganizationId') IS NULL
                    ALTER TABLE [QuestionUsages] ADD [OrganizationId] int NULL;
                IF COL_LENGTH('SubscriptionPlans', 'MaxMembers') IS NULL
                    ALTER TABLE [SubscriptionPlans] ADD [MaxMembers] int NOT NULL CONSTRAINT [DF_SubscriptionPlans_MaxMembers] DEFAULT 30;

                IF OBJECT_ID(N'[OrganizationMembers]', N'U') IS NULL
                BEGIN
                    CREATE TABLE [OrganizationMembers] (
                        [Id] int NOT NULL IDENTITY,
                        [OrganizationId] int NOT NULL,
                        [UserId] nvarchar(450) NOT NULL,
                        [RoleInOrganization] nvarchar(40) NOT NULL,
                        [JoinedAt] datetime2 NOT NULL CONSTRAINT [DF_OrganizationMembers_JoinedAt] DEFAULT SYSUTCDATETIME(),
                        CONSTRAINT [PK_OrganizationMembers] PRIMARY KEY ([Id]),
                        CONSTRAINT [FK_OrganizationMembers_Organizations_OrganizationId] FOREIGN KEY ([OrganizationId]) REFERENCES [Organizations] ([Id]) ON DELETE CASCADE,
                        CONSTRAINT [FK_OrganizationMembers_AspNetUsers_UserId] FOREIGN KEY ([UserId]) REFERENCES [AspNetUsers] ([Id]) ON DELETE CASCADE
                    );
                    CREATE UNIQUE INDEX [IX_OrganizationMembers_OrganizationId_UserId] ON [OrganizationMembers] ([OrganizationId], [UserId]);
                    CREATE INDEX [IX_OrganizationMembers_UserId] ON [OrganizationMembers] ([UserId]);
                END;

                IF OBJECT_ID(N'[OrganizationSubscriptions]', N'U') IS NULL
                BEGIN
                    CREATE TABLE [OrganizationSubscriptions] (
                        [Id] int NOT NULL IDENTITY,
                        [OrganizationId] int NOT NULL,
                        [PlanId] int NOT NULL,
                        [IsActive] bit NOT NULL,
                        [StartDate] datetime2 NOT NULL,
                        [EndDate] datetime2 NULL,
                        CONSTRAINT [PK_OrganizationSubscriptions] PRIMARY KEY ([Id]),
                        CONSTRAINT [FK_OrganizationSubscriptions_Organizations_OrganizationId] FOREIGN KEY ([OrganizationId]) REFERENCES [Organizations] ([Id]) ON DELETE CASCADE,
                        CONSTRAINT [FK_OrganizationSubscriptions_SubscriptionPlans_PlanId] FOREIGN KEY ([PlanId]) REFERENCES [SubscriptionPlans] ([Id]) ON DELETE CASCADE
                    );
                    CREATE INDEX [IX_OrganizationSubscriptions_OrganizationId_IsActive] ON [OrganizationSubscriptions] ([OrganizationId], [IsActive]);
                    CREATE INDEX [IX_OrganizationSubscriptions_PlanId] ON [OrganizationSubscriptions] ([PlanId]);
                END;

                IF OBJECT_ID(N'[BillingInvoices]', N'U') IS NULL
                BEGIN
                    CREATE TABLE [BillingInvoices] (
                        [Id] int NOT NULL IDENTITY,
                        [OrganizationId] int NOT NULL,
                        [PlanId] int NOT NULL,
                        [InvoiceNumber] nvarchar(40) NOT NULL,
                        [Amount] decimal(18,2) NOT NULL,
                        [Currency] nvarchar(8) NOT NULL,
                        [Status] nvarchar(30) NOT NULL,
                        [CreatedAt] datetime2 NOT NULL,
                        [PaidAt] datetime2 NULL,
                        CONSTRAINT [PK_BillingInvoices] PRIMARY KEY ([Id]),
                        CONSTRAINT [FK_BillingInvoices_Organizations_OrganizationId] FOREIGN KEY ([OrganizationId]) REFERENCES [Organizations] ([Id]) ON DELETE CASCADE,
                        CONSTRAINT [FK_BillingInvoices_SubscriptionPlans_PlanId] FOREIGN KEY ([PlanId]) REFERENCES [SubscriptionPlans] ([Id]) ON DELETE CASCADE
                    );
                    CREATE INDEX [IX_BillingInvoices_OrganizationId] ON [BillingInvoices] ([OrganizationId]);
                    CREATE INDEX [IX_BillingInvoices_PlanId] ON [BillingInvoices] ([PlanId]);
                END;

                IF OBJECT_ID(N'[CheckoutSessions]', N'U') IS NULL
                BEGIN
                    CREATE TABLE [CheckoutSessions] (
                        [Id] int NOT NULL IDENTITY,
                        [OrganizationId] int NOT NULL,
                        [PlanId] int NOT NULL,
                        [Status] nvarchar(30) NOT NULL,
                        [ReferenceCode] nvarchar(60) NOT NULL,
                        [Amount] decimal(18,2) NOT NULL,
                        [Currency] nvarchar(8) NOT NULL,
                        [CreatedAt] datetime2 NOT NULL,
                        [PaidAt] datetime2 NULL,
                        CONSTRAINT [PK_CheckoutSessions] PRIMARY KEY ([Id]),
                        CONSTRAINT [FK_CheckoutSessions_Organizations_OrganizationId] FOREIGN KEY ([OrganizationId]) REFERENCES [Organizations] ([Id]) ON DELETE CASCADE,
                        CONSTRAINT [FK_CheckoutSessions_SubscriptionPlans_PlanId] FOREIGN KEY ([PlanId]) REFERENCES [SubscriptionPlans] ([Id]) ON DELETE CASCADE
                    );
                    CREATE UNIQUE INDEX [IX_CheckoutSessions_ReferenceCode] ON [CheckoutSessions] ([ReferenceCode]);
                    CREATE INDEX [IX_CheckoutSessions_OrganizationId] ON [CheckoutSessions] ([OrganizationId]);
                    CREATE INDEX [IX_CheckoutSessions_PlanId] ON [CheckoutSessions] ([PlanId]);
                END;

                IF OBJECT_ID(N'[AuditLogs]', N'U') IS NULL
                BEGIN
                    CREATE TABLE [AuditLogs] (
                        [Id] int NOT NULL IDENTITY,
                        [ActorUserId] nvarchar(450) NULL,
                        [ActorEmail] nvarchar(256) NOT NULL,
                        [ActorRole] nvarchar(40) NOT NULL,
                        [Action] nvarchar(80) NOT NULL,
                        [EntityType] nvarchar(80) NOT NULL,
                        [EntityId] int NULL,
                        [SubjectId] int NULL,
                        [OrganizationId] int NULL,
                        [Summary] nvarchar(500) NOT NULL,
                        [CreatedAt] datetime2 NOT NULL CONSTRAINT [DF_AuditLogs_CreatedAt] DEFAULT SYSUTCDATETIME(),
                        CONSTRAINT [PK_AuditLogs] PRIMARY KEY ([Id])
                    );
                    CREATE INDEX [IX_AuditLogs_CreatedAt] ON [AuditLogs] ([CreatedAt]);
                    CREATE INDEX [IX_AuditLogs_OrganizationId_CreatedAt] ON [AuditLogs] ([OrganizationId], [CreatedAt]);
                    CREATE INDEX [IX_AuditLogs_SubjectId_CreatedAt] ON [AuditLogs] ([SubjectId], [CreatedAt]);
                END;
            """);
        }

        private static async Task SeedDefaultOrganizationAsync(ApplicationDbContext db)
        {
            var org = await db.Organizations.FirstOrDefaultAsync(o => o.Slug == "bluecloud-academy");
            if (org == null)
            {
                org = new Organization
                {
                    Name = "BlueCloud Academy",
                    Slug = "bluecloud-academy",
                    IsActive = true,
                    CreatedAt = DateTime.UtcNow
                };
                db.Organizations.Add(org);
                await db.SaveChangesAsync();
            }

            var freePlan = await db.SubscriptionPlans.FirstAsync(p => p.Name == AuthConstants.Free);
            var hasSubscription = await db.OrganizationSubscriptions.AnyAsync(s => s.OrganizationId == org.Id && s.IsActive);
            if (!hasSubscription)
            {
                db.OrganizationSubscriptions.Add(new OrganizationSubscription
                {
                    OrganizationId = org.Id,
                    PlanId = freePlan.Id,
                    IsActive = true,
                    StartDate = DateTime.UtcNow
                });
            }

            var subjectsWithoutOrg = await db.Subjects.Where(s => s.OrganizationId == null).ToListAsync();
            foreach (var subject in subjectsWithoutOrg)
            {
                subject.OrganizationId = org.Id;
            }

            await db.SaveChangesAsync();
        }

        private static async Task SeedRolesAsync(RoleManager<IdentityRole> roleManager)
        {
            foreach (var role in new[] { AuthConstants.Admin, AuthConstants.Lecturer, AuthConstants.Student })
            {
                if (!await roleManager.RoleExistsAsync(role))
                    await roleManager.CreateAsync(new IdentityRole(role));
            }
        }

        private static async Task SeedDemoUsersAsync(ApplicationDbContext db, UserManager<ApplicationUser> userManager)
        {
            await EnsureUserAsync(db, userManager, "admin@educhatbot.local", "Admin Demo", "Admin@12345!", AuthConstants.Admin);
            await EnsureUserAsync(db, userManager, "lecturer@educhatbot.local", "Lecturer Demo", "Lecturer@12345!", AuthConstants.Lecturer);
            await EnsureUserAsync(db, userManager, "student@educhatbot.local", "Student Demo", "Student@12345!", AuthConstants.Student);
        }

        private static async Task EnsureUserAsync(
            ApplicationDbContext db,
            UserManager<ApplicationUser> userManager,
            string email,
            string fullName,
            string password,
            string role)
        {
            var user = await userManager.FindByEmailAsync(email);
            if (user == null)
            {
                user = new ApplicationUser
                {
                    UserName = email,
                    Email = email,
                    FullName = fullName,
                    EmailConfirmed = true
                };
                await userManager.CreateAsync(user, password);
            }

            if (!await userManager.IsInRoleAsync(user, role))
                await userManager.AddToRoleAsync(user, role);

            var subjects = await db.Subjects.ToListAsync();
            var org = await db.Organizations.FirstAsync(o => o.Slug == "bluecloud-academy");
            var orgRole = role == AuthConstants.Admin ? AuthConstants.Admin : role;
            var orgMemberExists = await db.OrganizationMembers.AnyAsync(m => m.OrganizationId == org.Id && m.UserId == user.Id);
            if (!orgMemberExists)
            {
                db.OrganizationMembers.Add(new OrganizationMember
                {
                    OrganizationId = org.Id,
                    UserId = user.Id,
                    RoleInOrganization = orgRole,
                    JoinedAt = DateTime.UtcNow
                });
            }

            foreach (var subject in subjects)
            {
                if (role == AuthConstants.Admin)
                    continue;

                var exists = await db.SubjectMemberships.AnyAsync(m => m.SubjectId == subject.Id && m.UserId == user.Id);
                if (!exists)
                {
                    db.SubjectMemberships.Add(new SubjectMembership
                    {
                        SubjectId = subject.Id,
                        UserId = user.Id,
                        RoleInSubject = role
                    });
                }
            }

            await db.SaveChangesAsync();
        }
    }
}
