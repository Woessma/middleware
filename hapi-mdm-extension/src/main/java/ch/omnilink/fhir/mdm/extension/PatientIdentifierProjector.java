package ch.omnilink.fhir.mdm.extension;

import ca.uhn.fhir.jpa.api.dao.DaoRegistry;
import ca.uhn.fhir.jpa.api.dao.IFhirResourceDao;
import ca.uhn.fhir.jpa.dao.tx.HapiTransactionService;
import ca.uhn.fhir.jpa.model.dao.JpaPid;
import ca.uhn.fhir.mdm.api.IMdmLinkQuerySvc;
import ca.uhn.fhir.mdm.api.MdmMatchResultEnum;
import ca.uhn.fhir.mdm.api.paging.MdmPageRequest;
import ca.uhn.fhir.mdm.api.params.MdmQuerySearchParameters;
import ca.uhn.fhir.mdm.model.MdmTransactionContext;
import ca.uhn.fhir.mdm.util.MdmResourceUtil;
import ca.uhn.fhir.rest.api.RestOperationTypeEnum;
import ca.uhn.fhir.rest.api.server.SystemRequestDetails;
import ca.uhn.fhir.rest.server.TransactionLogMessages;
import jakarta.persistence.CacheRetrieveMode;
import jakarta.persistence.EntityManager;
import jakarta.persistence.EntityManagerFactory;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.hibernate.Session;
import org.hl7.fhir.r4.model.IdType;
import org.hl7.fhir.r4.model.Patient;
import org.springframework.orm.jpa.EntityManagerFactoryUtils;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionSynchronizationManager;

public final class PatientIdentifierProjector implements PatientProjectionWorker.Operations {
    private static final int SCAN_LIMIT = 1000;
    public record Claim(long eventId, UUID owner, long fence) {
        public Claim {
            if (eventId <= 0 || owner == null || fence <= 0) {
                throw new IllegalArgumentException("An owned projection claim is required");
            }
        }
    }
    public enum Status { APPLIED_NOT_PUBLISHED, REPLAY_NOT_PUBLISHED }
    public record Result(Status status, long eventId, int updates, int goldens, String transactionId) {}
    public enum PollStatus { RUNNABLE, BLOCKED_UNRESOLVED_CAPTURE, BLOCKED_RETRY_EXHAUSTED }
    public record Poll(PollStatus status, Optional<Claim> claim) {}
    public enum Recovery { ACKNOWLEDGED_NOT_PUBLISHED, RETRY_SCHEDULED, EXHAUSTED, CLAIM_LOST }
    private record PatientRow(long pid, String id, long version, boolean deleted) {}

    private final HapiTransactionService transactions;
    private final EntityManagerFactory factory;
    private final IFhirResourceDao<Patient> patients;
    private final IMdmLinkQuerySvc links;

    public PatientIdentifierProjector(HapiTransactionService transactions, EntityManagerFactory factory,
            DaoRegistry registry, IMdmLinkQuerySvc links) {
        if (!(transactions.getTransactionManager() instanceof JpaTransactionManager manager)
                || manager.getEntityManagerFactory() != factory) {
            throw new IllegalArgumentException("Projector must use the HAPI JPA transaction manager and factory");
        }
        this.transactions = transactions;
        this.factory = factory;
        this.patients = registry.getResourceDao(Patient.class);
        this.links = links;
    }

    public Optional<Claim> claim(UUID worker, int leaseMillis) {
        requireRoot();
        return transactions.withSystemRequest().withPropagation(Propagation.REQUIRES_NEW).execute(
                (TransactionCallback<Optional<Claim>>) status -> session().doReturningWork(connection -> {
                    configureConnection(connection);
                    return claim(connection, worker, leaseMillis);
                }));
    }

    @Override
    public Poll poll(UUID worker, int leaseMillis) {
        requireRoot();
        if (worker == null || leaseMillis < 100 || leaseMillis > 300000) {
            throw new IllegalArgumentException("Invalid Patient projection worker or lease");
        }
        return transactions.withSystemRequest().withPropagation(Propagation.REQUIRES_NEW).execute(
                (TransactionCallback<Poll>) status -> session().doReturningWork(connection -> {
                    configureConnection(connection);
                    String readiness;
                    try (var sql = connection.createStatement();
                            var rows = sql.executeQuery("SELECT omni_patient_projection_read_status()")) {
                        if (!rows.next()) {
                            throw new IllegalStateException("Patient projection status returned no row");
                        }
                        readiness = rows.getString(1);
                    }
                    return switch (readiness) {
                        case "BLOCKED_UNRESOLVED_CAPTURE" ->
                            new Poll(PollStatus.BLOCKED_UNRESOLVED_CAPTURE, Optional.empty());
                        case "BLOCKED_RETRY_EXHAUSTED" ->
                            new Poll(PollStatus.BLOCKED_RETRY_EXHAUSTED, Optional.empty());
                        case "BLOCKED_PROJECTION_PENDING", "BLOCKED_READER_NOT_PUBLISHED" ->
                            new Poll(PollStatus.RUNNABLE, claim(connection, worker, leaseMillis));
                        default -> throw new IllegalStateException("Unsupported Patient projector publication status");
                    };
                }));
    }

    @Override
    public Recovery recover(Claim claim, int delayMillis) {
        requireRoot();
        if (claim == null || delayMillis < 0 || delayMillis > 60000) {
            throw new IllegalArgumentException("An owned projection claim and bounded retry delay are required");
        }
        return transactions.withSystemRequest().withPropagation(Propagation.REQUIRES_NEW).execute(
                (TransactionCallback<Recovery>) status -> session().doReturningWork(connection -> {
                    configureConnection(connection);
                    try (var sql = connection.createStatement()) {
                        sql.execute("SELECT omni_projection_check_publisher()");
                    }
                    String jobState;
                    boolean live;
                    // This lock waits for any earlier apply holding the job, including an uncertain commit.
                    try (var sql = connection.prepareStatement("""
                            SELECT state,owner,fence,lease_until>clock_timestamp()
                            FROM omni_projection_job WHERE event_id=? FOR UPDATE
                            """)) {
                        sql.setLong(1, claim.eventId());
                        try (var rows = sql.executeQuery()) {
                            if (!rows.next() || !claim.owner().equals(rows.getObject(2, UUID.class))
                                    || claim.fence() != rows.getLong(3)) {
                                return Recovery.CLAIM_LOST;
                            }
                            jobState = rows.getString(1);
                            live = rows.getBoolean(4);
                        }
                    }
                    boolean receipt;
                    // A fresh statement sees the receipt committed by a previously blocked row owner.
                    try (var sql = connection.prepareStatement("""
                            SELECT 1 FROM omni_projection_receipt WHERE event_id=? AND owner=? AND fence=?
                            """)) {
                        bind(sql, claim);
                        try (var rows = sql.executeQuery()) {
                            receipt = rows.next();
                        }
                    }
                    if ("acknowledged".equals(jobState) && receipt) {
                        return Recovery.ACKNOWLEDGED_NOT_PUBLISHED;
                    }
                    if ("acknowledged".equals(jobState) || receipt) {
                        throw new IllegalStateException("Patient projection recovery has an inconsistent receipt");
                    }
                    if (!"leased".equals(jobState) || !live) {
                        return Recovery.CLAIM_LOST;
                    }
                    try (var sql = connection.prepareStatement(
                            "SELECT omni_projection_fail(?,?,?,'APPLY_FAILED',?)")) {
                        bind(sql, claim);
                        sql.setInt(4, delayMillis);
                        try (var rows = sql.executeQuery()) {
                            if (!rows.next()) {
                                throw new IllegalStateException("Patient projection retry returned no result");
                            }
                            return switch (rows.getString(1)) {
                                case "RETRY_SCHEDULED" -> Recovery.RETRY_SCHEDULED;
                                case "EXHAUSTED" -> Recovery.EXHAUSTED;
                                default -> throw new IllegalStateException("Unexpected Patient projection retry result");
                            };
                        }
                    }
                }));
    }

    private static Optional<Claim> claim(Connection connection, UUID worker, int leaseMillis) throws SQLException {
        try (var sql = connection.prepareStatement("SELECT * FROM omni_projection_claim(?,?)")) {
            sql.setObject(1, worker);
            sql.setInt(2, leaseMillis);
            try (var rows = sql.executeQuery()) {
                return rows.next()
                        ? Optional.of(new Claim(rows.getLong("event_id"), worker, rows.getLong("fence")))
                        : Optional.empty();
            }
        }
    }

    // Exceptions may include a lost post-commit response. Replay the claim; do not blindly schedule failure.
    public Result apply(Claim claim) {
        requireRoot();
        if (claim == null) {
            throw new IllegalArgumentException("An owned projection claim is required");
        }
        return transactions.withSystemRequest().withPropagation(Propagation.REQUIRES_NEW)
                .execute((TransactionCallback<Result>) status -> project(claim));
    }

    private Result project(Claim claim) {
        EntityManager em = entityManager();
        Session session = em.unwrap(Session.class);
        Result replay = session.doReturningWork(connection -> {
            configureConnection(connection);
            try (var sql = connection.createStatement()) {
                // Acquire all locks before the first input snapshot, in a separate SQL statement.
                sql.execute("SELECT omni_projection_lock_inputs()");
                sql.execute("SELECT omni_projection_check_publisher()");
            }
            try (var sql = connection.prepareStatement("""
                    SELECT j.state,j.owner,j.fence,j.lease_until>clock_timestamp(),
                        r.golden_updates,r.golden_count,r.transaction_id::text
                    FROM omni_projection_job j LEFT JOIN omni_projection_receipt r USING(event_id)
                    WHERE j.event_id=? FOR UPDATE OF j
                    """)) {
                sql.setLong(1, claim.eventId());
                try (var rows = sql.executeQuery()) {
                    if (!rows.next() || !claim.owner().equals(rows.getObject(2, UUID.class))
                            || rows.getLong(3) != claim.fence()) {
                        throw new IllegalStateException("Stale Patient projection claim");
                    }
                    if ("acknowledged".equals(rows.getString(1))) {
                        return new Result(Status.REPLAY_NOT_PUBLISHED, claim.eventId(),
                                rows.getInt(5), rows.getInt(6), rows.getString(7));
                    }
                    if (!"leased".equals(rows.getString(1)) || !rows.getBoolean(4)) {
                        throw new IllegalStateException("Expired or nonleased Patient projection claim");
                    }
                }
            }
            return null;
        });
        if (replay != null) {
            return replay;
        }
        em.clear();
        em.setProperty("jakarta.persistence.cache.retrieveMode", CacheRetrieveMode.BYPASS);
        List<PatientRow> inventory = session.doReturningWork(connection -> {
            var result = new ArrayList<PatientRow>();
            try (var sql = connection.prepareStatement("""
                    SELECT res_id,coalesce(fhir_id,res_id::text),res_ver,partition_id,
                        res_deleted_at IS NOT NULL FROM hfj_resource
                    WHERE res_type='Patient' ORDER BY res_id LIMIT ?
                    """)) {
                sql.setInt(1, SCAN_LIMIT + 1);
                try (var rows = sql.executeQuery()) {
                    while (rows.next()) {
                        if (rows.getObject(4) != null) {
                            throw new IllegalStateException("Patient projection does not support partitions");
                        }
                        result.add(new PatientRow(
                                rows.getLong(1), rows.getString(2), rows.getLong(3), rows.getBoolean(5)));
                    }
                }
            }
            if (result.size() > SCAN_LIMIT) {
                throw new IllegalStateException("Patient projector inventory bound exceeded");
            }
            return result;
        });
        Map<String, Patient> all = new LinkedHashMap<>();
        Map<String, Patient> goldens = new LinkedHashMap<>();
        Map<String, List<Patient>> sources = new LinkedHashMap<>();
        var deleted = new HashSet<String>();
        for (PatientRow row : inventory) {
            String reference = "Patient/" + row.id();
            if (row.deleted()) {
                deleted.add(reference);
                continue;
            }
            Patient patient = patients.readByPid(JpaPid.fromId(row.pid())).copy();
            if (!row.id().equals(patient.getIdElement().getIdPart())
                    || !Long.toString(row.version()).equals(patient.getIdElement().getVersionIdPart())
                    || all.putIfAbsent(reference, patient) != null) {
                throw new IllegalStateException("HAPI Patient does not match the locked inventory");
            }
            if (MdmResourceUtil.isGoldenRecord(patient) && !MdmResourceUtil.isGoldenRecordRedirected(patient)) {
                goldens.put(reference, patient);
                sources.put(reference, new ArrayList<>());
            }
        }
        var parameters = new MdmQuerySearchParameters(new MdmPageRequest(0, SCAN_LIMIT, SCAN_LIMIT, SCAN_LIMIT))
                .setResourceType("Patient").setMatchResult(MdmMatchResultEnum.MATCH);
        var context = new MdmTransactionContext(
                TransactionLogMessages.createFromTransactionGuid(UUID.randomUUID().toString()),
                MdmTransactionContext.OperationType.QUERY_LINKS, "Patient");
        var confirmed = links.queryLinks(parameters, context);
        if (confirmed.hasNext()) {
            throw new IllegalStateException("Patient projector MATCH set is incomplete");
        }
        var seen = new HashSet<String>();
        for (var link : confirmed.getContent()) {
            if (link.getMatchResult() != MdmMatchResultEnum.MATCH || !seen.add(link.getSourceId())) {
                throw new IllegalStateException("Ambiguous confirmed Patient link");
            }
            if (deleted.contains(link.getSourceId())) {
                continue;
            }
            Patient source = all.get(link.getSourceId());
            if (source == null || !goldens.containsKey(link.getGoldenResourceId())
                    || MdmResourceUtil.isGoldenRecord(source) || MdmResourceUtil.isGoldenRecordRedirected(source)) {
                throw new IllegalStateException("Ambiguous, deleted or unsupported confirmed Patient link");
            }
            sources.get(link.getGoldenResourceId()).add(source);
        }
        int updates = 0;
        for (var entry : goldens.entrySet()) {
            Patient projected = GoldenIdentifierReconciler.reconcile(entry.getValue(), sources.get(entry.getKey()));
            if (!entry.getValue().equalsDeep(projected)) {
                projected.setId(new IdType("Patient", entry.getValue().getIdElement().getIdPart(),
                        entry.getValue().getIdElement().getVersionIdPart()));
                var request = new SystemRequestDetails();
                request.setRestOperationType(RestOperationTypeEnum.UPDATE);
                patients.update(projected, request);
                updates++;
            }
        }
        em.flush();
        int appliedUpdates = updates;
        return session.doReturningWork(connection -> {
            try (var sql = connection.prepareStatement("SELECT omni_projection_complete(?,?,?,?,?)")) {
                bind(sql, claim);
                sql.setInt(4, appliedUpdates);
                sql.setInt(5, goldens.size());
                sql.execute();
            }
            try (var sql = connection.prepareStatement(
                    "SELECT transaction_id::text FROM omni_projection_receipt WHERE event_id=?")) {
                sql.setLong(1, claim.eventId());
                try (var rows = sql.executeQuery()) {
                    if (!rows.next()) {
                        throw new IllegalStateException("Patient projection completion has no receipt");
                    }
                    return new Result(Status.APPLIED_NOT_PUBLISHED, claim.eventId(),
                            appliedUpdates, goldens.size(), rows.getString(1));
                }
            }
        });
    }

    private EntityManager entityManager() {
        EntityManager em = EntityManagerFactoryUtils.getTransactionalEntityManager(factory);
        // Spring's application-managed proxy reports "joined" differently for resource-local transactions.
        if (em == null || !TransactionSynchronizationManager.isActualTransactionActive()
                || !em.getTransaction().isActive()) {
            throw new IllegalStateException("Projector has no active HAPI EntityManager transaction");
        }
        return em;
    }

    private Session session() {
        return entityManager().unwrap(Session.class);
    }

    private static void requireRoot() {
        if (TransactionSynchronizationManager.isActualTransactionActive()
                || TransactionSynchronizationManager.isSynchronizationActive()) {
            throw new IllegalStateException("Patient projection requires a separate root transaction");
        }
    }

    private static void bind(PreparedStatement sql, Claim claim) throws SQLException {
        sql.setLong(1, claim.eventId());
        sql.setObject(2, claim.owner());
        sql.setLong(3, claim.fence());
    }

    private static void configureConnection(Connection connection) throws SQLException {
        if (connection.getAutoCommit() || connection.isReadOnly()
                || connection.getTransactionIsolation() != Connection.TRANSACTION_READ_COMMITTED) {
            throw new IllegalStateException("Projector requires a writable READ COMMITTED HAPI transaction");
        }
        try (var sql = connection.createStatement()) {
            sql.execute("SET LOCAL lock_timeout='2s'; SET LOCAL statement_timeout='15s';"
                    + "SET LOCAL idle_in_transaction_session_timeout='20s'");
        }
    }
}
