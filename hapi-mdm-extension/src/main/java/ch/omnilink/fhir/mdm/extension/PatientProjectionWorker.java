package ch.omnilink.fhir.mdm.extension;

import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.Claim;
import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.Poll;
import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.Recovery;
import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.Result;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;

public final class PatientProjectionWorker {
    public interface Operations {
        Poll poll(UUID worker, int leaseMillis);
        Result apply(Claim claim);
        Recovery recover(Claim claim, int delayMillis);
    }

    public enum Phase {
        STARTING, IDLE, PROCESSING, APPLIED_NOT_PUBLISHED, ACKNOWLEDGED_NOT_PUBLISHED,
        RETRY_SCHEDULED, BLOCKED_UNRESOLVED_CAPTURE, BLOCKED_RETRY_EXHAUSTED,
        CLAIM_LOST, CLAIM_OUTCOME_UNKNOWN, APPLY_OUTCOME_UNKNOWN, RECOVERY_OUTCOME_UNKNOWN
    }
    public record State(Phase phase, Instant observedAt, Instant lastCompletionObservedAt,
                        Long eventId, Long fence, String failureType) {}

    private static final Logger LOG = LoggerFactory.getLogger(PatientProjectionWorker.class);
    private final UUID owner = UUID.randomUUID();
    private final Operations operations;
    private volatile State state = new State(Phase.STARTING, Instant.now(), null, null, null, null);

    public PatientProjectionWorker(Operations operations) {
        this.operations = Objects.requireNonNull(operations);
    }

    public State state() {
        return state;
    }

    @Scheduled(fixedDelay = 1000, initialDelay = 1000)
    public synchronized void tick() {
        Poll poll;
        try {
            poll = operations.poll(owner, 30000);
        } catch (RuntimeException failure) {
            failure(Phase.CLAIM_OUTCOME_UNKNOWN, null, failure);
            return;
        }
        switch (poll.status()) {
            case BLOCKED_UNRESOLVED_CAPTURE -> {
                blocked(Phase.BLOCKED_UNRESOLVED_CAPTURE);
                return;
            }
            case BLOCKED_RETRY_EXHAUSTED -> {
                blocked(Phase.BLOCKED_RETRY_EXHAUSTED);
                return;
            }
            case RUNNABLE -> { }
        }
        if (poll.claim().isEmpty()) {
            update(Phase.IDLE, null, null);
            return;
        }
        Claim claim = poll.claim().orElseThrow();
        update(Phase.PROCESSING, claim, null);
        try {
            Result result = operations.apply(claim);
            update(switch (result.status()) {
                case APPLIED_NOT_PUBLISHED -> Phase.APPLIED_NOT_PUBLISHED;
                case REPLAY_NOT_PUBLISHED -> Phase.ACKNOWLEDGED_NOT_PUBLISHED;
            }, claim, null);
            LOG.info("MDM projection completion observed; status={} event_id={} fence={} receipt_updates={} receipt_goldens={}",
                    result.status(), claim.eventId(), claim.fence(), result.updates(), result.goldens());
        } catch (RuntimeException failure) {
            failure(Phase.APPLY_OUTCOME_UNKNOWN, claim, failure);
            recover(claim);
        }
    }

    private void recover(Claim claim) {
        Recovery recovery;
        try {
            recovery = operations.recover(claim, 5000);
        } catch (RuntimeException failure) {
            failure(Phase.RECOVERY_OUTCOME_UNKNOWN, claim, failure);
            return;
        }
        switch (recovery) {
            case ACKNOWLEDGED_NOT_PUBLISHED -> {
                update(Phase.ACKNOWLEDGED_NOT_PUBLISHED, claim, null);
                LOG.warn("MDM projection response was uncertain; receipt confirmed event_id={} fence={}",
                        claim.eventId(), claim.fence());
            }
            case RETRY_SCHEDULED -> {
                update(Phase.RETRY_SCHEDULED, claim, null);
                LOG.warn("MDM projection retry scheduled; event_id={} fence={}", claim.eventId(), claim.fence());
            }
            case EXHAUSTED -> blocked(Phase.BLOCKED_RETRY_EXHAUSTED);
            case CLAIM_LOST -> {
                update(Phase.CLAIM_LOST, claim, null);
                LOG.warn("MDM projection claim no longer owned; event_id={} fence={}", claim.eventId(), claim.fence());
            }
        }
    }

    private void blocked(Phase phase) {
        if (state.phase() != phase) {
            LOG.error("MDM projection worker blocked; reason={}", phase);
        }
        update(phase, null, null);
    }

    private void failure(Phase phase, Claim claim, RuntimeException failure) {
        String type = failure.getClass().getName();
        Long event = claim == null ? null : claim.eventId();
        if (state.phase() != phase || !Objects.equals(state.failureType(), type)
                || !Objects.equals(state.eventId(), event)) {
            LOG.error("MDM projection worker outcome uncertain; phase={} event_id={} fence={} exception_type={}",
                    phase, event, claim == null ? null : claim.fence(), type);
        }
        update(phase, claim, type);
    }

    private void update(Phase phase, Claim claim, String failureType) {
        Instant now = Instant.now();
        Instant completed = phase == Phase.APPLIED_NOT_PUBLISHED || phase == Phase.ACKNOWLEDGED_NOT_PUBLISHED
                ? now : state.lastCompletionObservedAt();
        state = new State(phase, now, completed,
                claim == null ? null : claim.eventId(), claim == null ? null : claim.fence(), failureType);
    }
}
