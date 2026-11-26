package ch.omnilink.fhir.mdm.extension;

import static org.junit.jupiter.api.Assertions.*;

import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.*;
import ch.omnilink.fhir.mdm.extension.PatientProjectionWorker.Phase;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

class PatientProjectionWorkerTest {
    @Test
    void idleAndBlockedPollsNeverApplyWork() {
        FakeWork work = new FakeWork();
        work.hasWork = false;
        var worker = new PatientProjectionWorker(work);
        worker.tick();
        assertEquals(Phase.IDLE, worker.state().phase());
        work.pollStatus = PollStatus.BLOCKED_UNRESOLVED_CAPTURE;
        worker.tick();
        assertEquals(Phase.BLOCKED_UNRESOLVED_CAPTURE, worker.state().phase());
        work.pollStatus = PollStatus.BLOCKED_RETRY_EXHAUSTED;
        worker.tick();
        assertEquals(Phase.BLOCKED_RETRY_EXHAUSTED, worker.state().phase());
        assertEquals(0, work.applications);
        assertEquals(0, work.recoveries);
        assertNull(worker.state().lastCompletionObservedAt());
    }

    @Test
    void successfulApplyDoesNotScheduleFailureOrRecovery() {
        FakeWork work = new FakeWork();
        var worker = new PatientProjectionWorker(work);
        worker.tick();
        assertEquals(Phase.APPLIED_NOT_PUBLISHED, worker.state().phase());
        assertNotNull(worker.state().lastCompletionObservedAt());
        assertEquals(1, work.applications);
        assertEquals(0, work.recoveries);
    }

    @Test
    void anUncertainClaimCannotBeAppliedOrFailedWithoutAnOwnedToken() {
        FakeWork work = new FakeWork();
        work.claimFailure = true;
        var worker = new PatientProjectionWorker(work);
        worker.tick();
        assertEquals(Phase.CLAIM_OUTCOME_UNKNOWN, worker.state().phase());
        assertEquals(0, work.applications);
        assertEquals(0, work.recoveries);
        assertNull(worker.state().lastCompletionObservedAt());
    }

    @ParameterizedTest
    @EnumSource(Recovery.class)
    void applyFailureUsesReceiptAwareRecoveryRatherThanBlindReapplication(Recovery recovery) {
        FakeWork work = new FakeWork();
        work.applyFailure = true;
        work.recovery = recovery;
        var worker = new PatientProjectionWorker(work);
        worker.tick();
        assertEquals(switch (recovery) {
            case ACKNOWLEDGED_NOT_PUBLISHED -> Phase.ACKNOWLEDGED_NOT_PUBLISHED;
            case RETRY_SCHEDULED -> Phase.RETRY_SCHEDULED;
            case EXHAUSTED -> Phase.BLOCKED_RETRY_EXHAUSTED;
            case CLAIM_LOST -> Phase.CLAIM_LOST;
        }, worker.state().phase());
        assertEquals(1, work.applications);
        assertEquals(1, work.recoveries);
        assertEquals(recovery == Recovery.ACKNOWLEDGED_NOT_PUBLISHED,
                worker.state().lastCompletionObservedAt() != null);
    }

    @Test
    void anUncertainRecoveryLeavesTheDurableLeaseProtocolInCharge() {
        FakeWork work = new FakeWork();
        work.applyFailure = true;
        work.recoveryFailure = true;
        var worker = new PatientProjectionWorker(work);
        worker.tick();
        assertEquals(Phase.RECOVERY_OUTCOME_UNKNOWN, worker.state().phase());
        assertEquals(IllegalStateException.class.getName(), worker.state().failureType());
        assertNull(worker.state().lastCompletionObservedAt());
        assertEquals(1, work.applications);
        assertEquals(1, work.recoveries);
        work.hasWork = false;
        worker.tick();
        assertEquals(1, work.applications, "The same uncertain lease must not be blindly applied again");
    }

    @Test
    void historicalReplayIsNotReportedAsANewProjection() {
        FakeWork work = new FakeWork();
        work.applyStatus = Status.REPLAY_NOT_PUBLISHED;
        var worker = new PatientProjectionWorker(work);
        worker.tick();
        assertEquals(Phase.ACKNOWLEDGED_NOT_PUBLISHED, worker.state().phase());
        assertEquals(1, work.applications);
        assertEquals(0, work.recoveries);
    }

    private static class FakeWork implements PatientProjectionWorker.Operations {
        boolean hasWork = true;
        boolean claimFailure;
        boolean applyFailure;
        boolean recoveryFailure;
        int applications;
        int recoveries;
        PollStatus pollStatus = PollStatus.RUNNABLE;
        Recovery recovery = Recovery.RETRY_SCHEDULED;
        Status applyStatus = Status.APPLIED_NOT_PUBLISHED;

        @Override
        public Poll poll(UUID worker, int leaseMillis) {
            if (claimFailure) {
                throw new IllegalStateException("Synthetic lost claim response");
            }
            return new Poll(pollStatus, hasWork && pollStatus == PollStatus.RUNNABLE
                    ? Optional.of(new Claim(1, worker, 1)) : Optional.empty());
        }

        @Override
        public Result apply(Claim claim) {
            applications++;
            if (applyFailure) {
                throw new IllegalStateException("Synthetic uncertain apply");
            }
            return new Result(applyStatus, claim.eventId(), 1, 1, "123");
        }

        @Override
        public Recovery recover(Claim claim, int delayMillis) {
            recoveries++;
            if (recoveryFailure) {
                throw new IllegalStateException("Synthetic uncertain recovery");
            }
            return recovery;
        }
    }
}
