package ch.omnilink.fhir.mdm.extension;

import ca.uhn.fhir.jpa.entity.MdmLink;
import ca.uhn.fhir.jpa.mdm.dao.MdmLinkDaoSvc;
import ca.uhn.fhir.jpa.model.dao.JpaPid;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronizationManager;

public class AtomicMergeMdmLinkDaoSvc extends MdmLinkDaoSvc<JpaPid, MdmLink> {
    private final MdmLinkDaoSvc<JpaPid, MdmLink> delegate;

    public AtomicMergeMdmLinkDaoSvc(MdmLinkDaoSvc<JpaPid, MdmLink> delegate) {
        this.delegate = delegate;
    }

    @Override
    @Transactional(propagation = Propagation.SUPPORTS)
    public void deleteLink(MdmLink link) {
        if (!GoldenManualIdentifierPolicy.mergeActive()) {
            delegate.deleteLink(link);
            return;
        }
        if (!TransactionSynchronizationManager.isActualTransactionActive()) {
            throw new IllegalStateException("Golden merge link deletion requires the HAPI transaction");
        }
        // A direct super call avoids the native REQUIRES_NEW proxy only inside the protected merge scope.
        super.deleteLink(link);
    }
}
